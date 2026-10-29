"""Git worktree yönetimi ve İki Aşamalı Güvenli Birleştirme (§15).

Hiçbir koşulda kullanıcının çalışma kopyasını bozmaz.
Kullanıcının hedef reposunda checkout, reset --hard, stash, push --force,
branch -f main ve otomatik git push KESİNLİKLE YASAKTIR.
"""

import sys
import os
import subprocess
import fnmatch
import hashlib
import time
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

from agentbus.db import transition
from agentbus.models import JobStatus, Job, utc_now_iso
from agentbus.store.jobs import JobsStore
from agentbus.store.meta import MetaStore
from agentbus.store.events import EventsStore
from agentbus.profiles import RepoProfile, load_profile


def run_git(cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
    """Git komutunu UTF-8 olarak güvenle çalıştırır."""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        ["git"] + cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def get_repo_id(repo_path: Path) -> str:
    """Repo yolundan 8 karakterlik benzersiz repo kimliği üretir."""
    norm = str(repo_path.resolve()).lower()
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:8]


def create_worktree(
    repo_path: Path,
    job_id: str,
    worktrees_dir: Path,
    base_commit: Optional[str] = None
) -> Tuple[Path, str, str]:
    """İş için izole bir git worktree ve dal oluşturur."""
    worktrees_dir.mkdir(parents=True, exist_ok=True)
    wt_path = worktrees_dir / job_id
    branch_name = f"agentbus/{job_id}"

    if not base_commit:
        rc, out, err = run_git(["rev-parse", "HEAD"], cwd=repo_path)
        if rc != 0:
            raise RuntimeError(f"Git HEAD alınamadı: {err}")
        base_commit = out

    # Eğer worktree zaten varsa döndür
    if wt_path.exists():
        return wt_path, branch_name, base_commit

    # worktree add
    rc, out, err = run_git(
        ["worktree", "add", "-b", branch_name, str(wt_path), base_commit],
        cwd=repo_path
    )
    if rc != 0:
        # Belki dal önceden vardı
        rc2, out2, err2 = run_git(
            ["worktree", "add", str(wt_path), branch_name],
            cwd=repo_path
        )
        if rc2 != 0:
            raise RuntimeError(f"Worktree oluşturulamadı: {err} | {err2}")

    return wt_path, branch_name, base_commit


def remove_worktree(repo_path: Path, worktree_path: Path, branch_name: Optional[str] = None) -> bool:
    """Worktree'yi güvenle kaldırır."""
    if not worktree_path.exists():
        return True
    rc, out, err = run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=repo_path)
    if branch_name:
        run_git(["branch", "-D", branch_name], cwd=repo_path)
    return rc == 0


def get_diff(worktree_path: Path, base_commit: Optional[str] = None) -> str:
    """Worktree değişikliklerinin unified diff'ini döndürür (untracked dosyalar dahil)."""
    if not worktree_path.exists():
        return ""
    # Yeni eklenen dosyaları da diff çıktısına dahil etmek için intent-to-add
    run_git(["add", "-N", "."], cwd=worktree_path)
    if base_commit:
        rc, out, _ = run_git(["diff", base_commit], cwd=worktree_path)
        return out
    rc, out, _ = run_git(["diff", "HEAD"], cwd=worktree_path)
    return out


def check_allowed_paths(
    worktree_path: Path,
    base_commit: str,
    allowed_globs: List[str]
) -> List[str]:
    """G12: base_commit..HEAD ve çalışma ağacındaki dosyaların izinli glob'lara uyumunu denetler.
    
    İzin dışı dosya varsa bu dosyaların listesini döndürür. Liste boşsa tüm dosyalar izinlidir.
    """
    if not allowed_globs:
        return []

    # 1. base_commit..HEAD arasındaki commit edilmiş dosyalar
    rc, out_committed, _ = run_git(["diff", "--name-only", f"{base_commit}..HEAD"], cwd=worktree_path)
    # 2. Çalışma ağacındaki uncommitted dosyalar
    rc, out_working, _ = run_git(["diff", "--name-only"], cwd=worktree_path)
    # 3. Untracked dosyalar
    rc, out_untracked, _ = run_git(["status", "--porcelain"], cwd=worktree_path)

    all_files = set()
    for line in out_committed.splitlines():
        if line.strip():
            all_files.add(line.strip().replace("\\", "/"))
    for line in out_working.splitlines():
        if line.strip():
            all_files.add(line.strip().replace("\\", "/"))
    for line in out_untracked.splitlines():
        if line.startswith("??"):
            all_files.add(line[3:].strip().replace("\\", "/"))

    disallowed = []
    for f in all_files:
        matched = False
        for glob_pat in allowed_globs:
            norm_glob = glob_pat.strip().replace("\\", "/")
            if fnmatch.fnmatch(f, norm_glob):
                matched = True
                break
        if not matched:
            disallowed.append(f)

    return disallowed


def get_or_create_integration_worktree(
    repo_path: Path,
    home_dir: Path
) -> Tuple[Path, str]:
    """§15 Aşama 1: Hedef repo için tekil entegrasyon worktree'sini hazırlar."""
    repo_id = get_repo_id(repo_path)
    integration_dir = home_dir / "integration" / repo_id
    integration_branch = "agentbus/integration"

    if integration_dir.exists():
        return integration_dir, integration_branch

    integration_dir.parent.mkdir(parents=True, exist_ok=True)

    # agentbus/integration dalı var mı?
    rc, _, _ = run_git(["rev-parse", "--verify", integration_branch], cwd=repo_path)
    if rc != 0:
        # main dalının ucundan oluştur
        run_git(["branch", integration_branch, "main"], cwd=repo_path)

    rc, out, err = run_git(
        ["worktree", "add", str(integration_dir), integration_branch],
        cwd=repo_path
    )
    if rc != 0:
        raise RuntimeError(f"Entegrasyon worktree'si oluşturulamadı: {err}")

    return integration_dir, integration_branch


def integrate_job(
    conn,
    home_dir: Path,
    job: Job,
    repo_profile: Optional[RepoProfile] = None
) -> Tuple[bool, str]:
    """§15 Aşama 1: İş dalını entegrasyon worktree'sine güvenle birleştirir.
    
    1. allowed_paths denetimi (G12).
    2. Entegrasyon worktree'sinde sıra kilidi.
    3. Rebase (G7) + merge --no-ff.
    4. Repo profilindeki test komutunu koşar (G5).
    5. Hata olursa abort ve önceki commite geri alma.
    """
    if not job.repo:
        return False, "İş için hedef repo (repo) tanımlı değil."

    repo_path = Path(job.repo).resolve()
    if not repo_path.exists():
        return False, f"Hedef repo dizini bulunamadı: {repo_path}"

    profile = repo_profile or load_profile(profile_name=job.agent_profile)

    # G12: allowed_paths denetimi
    if job.allowed_paths and job.worktree_path and job.base_commit:
        disallowed = check_allowed_paths(
            Path(job.worktree_path),
            job.base_commit,
            job.allowed_paths
        )
        if disallowed:
            return False, f"İzin verilmeyen dosya yollarına yazılmış (G12 kuralı ihlali): {disallowed}"

    meta_store = MetaStore(conn)
    events_store = EventsStore(conn)
    jobs_store = JobsStore(conn)

    repo_id = get_repo_id(repo_path)
    lock_key = f"integration_lock:{repo_id}"

    # Repo kilidi kontrolü (60 saniye kira süresi)
    existing_lock = meta_store.get(lock_key)
    if existing_lock:
        try:
            parts = existing_lock.split(":")
            ts_str = ":".join(parts[1:])
            from datetime import datetime, timezone
            lock_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            if (now_dt - lock_dt).total_seconds() > 60:
                meta_store.delete(lock_key)
            else:
                return False, f"Bu repo için başka bir entegrasyon işlemi sürüyor (Kilit: {existing_lock})"
        except Exception:
            meta_store.delete(lock_key)

    meta_store.set(lock_key, f"{job.id}:{utc_now_iso()}")

    try:
        integration_wt, int_branch = get_or_create_integration_worktree(repo_path, home_dir)

        # K-G6d: Yarım kalmış önceki merge/rebase durumlarını temizle
        run_git(["merge", "--abort"], cwd=integration_wt)
        run_git(["rebase", "--abort"], cwd=integration_wt)

        # 1. Entegrasyon dalının önceki commit kimliğini al (geri alma noktası)
        _, prev_head, _ = run_git(["rev-parse", "HEAD"], cwd=integration_wt)

        # 2. main ilerlediyse entegrasyon dalını main'e ff-merge et
        run_git(["merge", "--ff-only", "main"], cwd=integration_wt)

        # 3. Rebase (G7): İş worktree'sini entegrasyon dalının üzerine rebase et
        if job.worktree_path:
            wt_path = Path(job.worktree_path)
            # Çalışma ağacında commit edilmemiş değişiklikler varsa otomatik commit'le
            rc_st, out_st, _ = run_git(["status", "--porcelain"], cwd=wt_path)
            if out_st.strip():
                run_git(["add", "-A"], cwd=wt_path)
                run_git(["commit", "-m", f"Agent bus automated commit for {job.id}"], cwd=wt_path)

            rc_reb, _, err_reb = run_git(["rebase", int_branch], cwd=wt_path)
            if rc_reb != 0:
                run_git(["rebase", "--abort"], cwd=wt_path)
                transition(conn, job.id, job.status, JobStatus.CONFLICT, reason=f"Rebase çakışması: {err_reb}")
                return False, f"İş dalı entegrasyon dalı ile çakıştı (Rebase conflict): {err_reb}"

        # 4. Entegrasyon dalına merge et (merge --no-ff)
        branch_name = job.branch or f"agentbus/{job.id}"
        merge_msg = f"Merge job {job.id}: {job.title}"
        rc_mrg, _, err_mrg = run_git(
            ["merge", "--no-ff", branch_name, "-m", merge_msg],
            cwd=integration_wt
        )
        if rc_mrg != 0:
            run_git(["merge", "--abort"], cwd=integration_wt)
            run_git(["reset", "--hard", prev_head], cwd=integration_wt)
            transition(conn, job.id, job.status, JobStatus.CONFLICT, reason=f"Merge çakışması: {err_mrg}")
            return False, f"Merge çakışması: {err_mrg}"

        # 5. Repo profili test komutunu entegrasyon worktree'sinde çalıştır (G5)
        if profile.test_command:
            test_proc = subprocess.run(
                profile.test_command,
                cwd=str(integration_wt),
                shell=True,
                capture_output=True,
                text=True
            )
            if test_proc.returncode != 0:
                # Test başarısız! Entegrasyon dalını önceki commit'e geri al!
                run_git(["reset", "--hard", prev_head], cwd=integration_wt)
                transition(conn, job.id, job.status, JobStatus.TESTS_FAILED, reason=f"Entegrasyon testleri başarısız: {test_proc.stderr}")
                return False, f"Entegrasyon testleri başarısız oldu: {test_proc.stderr or test_proc.stdout}"

        # 6. Başarılı! Yeni merge commit'i kaydet
        _, new_head, _ = run_git(["rev-parse", "HEAD"], cwd=integration_wt)
        jobs_store.update_job(job.id, result_summary=f"Entegrasyon commit: {new_head[:8]}")
        transition(conn, job.id, job.status, JobStatus.INTEGRATED, reason=f"Entegrasyon dalına başarıyla birleştirildi ({new_head[:8]})")
        events_store.emit_event(
            "job.integrated",
            job_id=job.id,
            payload={"merge_commit": new_head, "repo": str(repo_path)}
        )
        return True, f"Başarıyla entegre edildi: {new_head[:8]}"

    finally:
        meta_store.delete(lock_key)


def promote_repo(
    conn,
    home_dir: Path,
    repo_path: Path
) -> Tuple[bool, str]:
    """§15 Aşama 2: Entegrasyon dalını kullanıcının main dalına terfi eder.
    
    Yalnız fast-forward terfi yapılır.
    Kullanıcının çalışma kopyası kirli ise ASLA dokunulmaz!
    """
    repo_path = repo_path.resolve()
    integration_dir, int_branch = get_or_create_integration_worktree(repo_path, home_dir)

    _, int_head, _ = run_git(["rev-parse", "HEAD"], cwd=integration_dir)
    _, main_head, _ = run_git(["rev-parse", "main"], cwd=repo_path)

    if int_head == main_head:
        return True, "Entegrasyon dalı zaten main ile senkronize. Terfi edilecek yeni commit yok."

    # Fast-forward kontrolü: main, entegrasyon dalının atası olmalı
    rc_anc, _, _ = run_git(["merge-base", "--is-ancestor", main_head, int_head], cwd=repo_path)
    if rc_anc != 0:
        return False, "Terfi başarısız: main entegrasyon dalının doğrudan atası değil (Fast-forward mümkün değil)."

    # Kullanıcının reposunda hangi dal açık?
    _, current_branch, _ = run_git(["branch", "--show-current"], cwd=repo_path)

    if current_branch == "main":
        # Kullanıcının açık çalışma kopyasında main açık!
        # Çalışma ağacı tamamen temiz mi kontrol et
        _, status_out, _ = run_git(["status", "--porcelain"], cwd=repo_path)
        if status_out.strip():
            # K-G6a: Kirli çalışma kopyası -> ASLA dokunma!
            return False, "Terfi durduruldu: Kullanıcının çalışma kopyası KİRLİ (değişiklikler var). Güvenlik gereği dokunulmadı."

        # Temiz ise fast-forward merge yap
        rc_ff, out_ff, err_ff = run_git(["merge", "--ff-only", int_branch], cwd=repo_path)
        if rc_ff != 0:
            return False, f"Fast-forward merge başarısız: {err_ff}"
    else:
        # main kullanıcının çalışma kopyasında checkout edilmiş değil!
        # update-ref ile güvenle ilerlet
        rc_ref, _, err_ref = run_git(["update-ref", "refs/heads/main", int_head], cwd=repo_path)
        if rc_ref != 0:
            return False, f"update-ref başarısız: {err_ref}"

    # Bu repoya ait tüm integrated işleri PROMOTED yap
    jobs_store = JobsStore(conn)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM jobs WHERE repo = ? AND status = 'integrated'", (str(repo_path),))
    for r in cursor.fetchall():
        try:
            transition(conn, r["id"], JobStatus.INTEGRATED, JobStatus.PROMOTED, reason=f"Main dalına terfi edildi ({int_head[:8]})")
        except Exception:
            pass

    return True, f"Başarıyla main dalına terfi edildi: {int_head[:8]}"


def revert_job(
    conn,
    home_dir: Path,
    job: Job
) -> Tuple[bool, str]:
    """Entegrasyon dalında işin merge commit'ini geri alır (git revert -m 1)."""
    if not job.repo:
        return False, "Hedef repo tanımlı değil."
    repo_path = Path(job.repo).resolve()
    integration_dir, _ = get_or_create_integration_worktree(repo_path, home_dir)

    # İlgili merge commit'i bul
    rc, log_out, _ = run_git(
        ["log", "--grep", f"Merge job {job.id}:", "-n", "1", "--format=%H"],
        cwd=integration_dir
    )
    merge_commit = log_out.strip()
    if not merge_commit:
        return False, f"İş [{job.id}] için merge commit bulunamadı."

    rc_rev, _, err_rev = run_git(
        ["revert", "-m", "1", "--no-edit", merge_commit],
        cwd=integration_dir
    )
    if rc_rev != 0:
        run_git(["revert", "--abort"], cwd=integration_dir)
        return False, f"Geri alma (revert) çakışması: {err_rev}"

    return True, f"İş [{job.id}] merge commit'i ({merge_commit[:8]}) başarıyla geri alındı."


def gc_worktrees(
    conn,
    home_dir: Path,
    repo_path: Path
) -> int:
    """Tamamlanmış (promoted / cancelled) işlerin worktree'lerini temizler."""
    repo_path = repo_path.resolve()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, worktree_path, branch FROM jobs WHERE repo = ? AND status IN ('promoted', 'cancelled')",
        (str(repo_path),)
    )
    rows = cursor.fetchall()
    cleaned = 0
    for r in rows:
        wt_path = Path(r["worktree_path"]) if r["worktree_path"] else None
        if wt_path and wt_path.exists():
            if remove_worktree(repo_path, wt_path, r["branch"]):
                cleaned += 1
    return cleaned
