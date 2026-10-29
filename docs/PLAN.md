# AGENT BUS — Proje Planı

Durum: **SON HAL — uygulamaya hazır (kod yok)** · Tarih: 2026-10-29 · Sahip: trace-corp24

> Tek cümle: Bir **üst yapay zekâ** (Claude Code), CLI üzerinden çalışan çok sayıda
> **Antigravity (`agy`) ajanını** ortak, kalıcı bir **ajan otobüsü (agent bus)** üzerinden
> yönetir; her aşama diske kaydedilir, kesintide kaldığı yerden devam eder, ortak
> durum her an izlenebilir ve istenen ajan oturumu insan tarafından CLI'da açılabilir.

---

## 0. Kullanıcı istekleri (birebir)
| # | İstek |
|---|-------|
| U1 | agy ajanlarını yöneten bir üst yapay zekâ olacak. |
| U2 | Her şey CLI ile çalışacak ve birbirine bağlı olacak. |
| U3 | Proje masaüstünde `agent_bus` klasöründe yapılacak. |
| U4 | Plan çok detaylı olacak. |
| U5 | `minion-cli-main` bu projeye evrilebilir mi analiz edilecek; altyapısı kullanılacak ama değiştirilecek. |
| U6 | Ortak durum izlenecek. |
| U7 | Kesintiye/durmaya dayanıklı; her aşama doğru şekilde kaydedilecek. |
| U8 | Gerektiğinde ilgili CLI (agy oturumu) yeniden açılabilecek. |
| U9 | (önceki tur) İzin: tam otomatik · İzolasyon: iş başına git worktree · Paralellik: en çok 4. |
| U10 | Şimdilik yalnız plan; derli toplu, düzenli, **tek klasörde** (`Desktop\agent_bus`). |
| U11 | minion-cli evrilebilir ya da parçaları alınabilir — hangisi mantıklıysa. |
| U12 | **Tüm ajanlar CLI'da gömülü olarak görülebilmeli** (her ajan ekranda canlı). |

### Kararlar (2026-10-29)
- Hedef repo **iş başına seçilir** (`--repo` / plan.yaml `repo:`); tek repoya bağlı değil.
- Veri: `Desktop\agent_bus\.data\` (bus.db, runs, worktrees) — `.gitignore`'da.
- İzleme: önce `watch`, ardından TUI; **ancak U12 gereği TUI zorunlu ve ana ekran** (opsiyonel değil).
- minion-cli: **parça alma** (gerekçe §2). Her şey `agent_bus` klasöründe toplanır; minion-cli-main'e dokunulmaz.
- Şimdilik kod yok; plan onaylanınca F0'dan başlanır.
- **Model:** tüm ajanlar `--model gemini-3.8-flash-high` (Gemini 3.8 Flash High; `agy models` ile doğrulandı).
  Varsayılan profil `default` bu modeli kullanır; profil yapısı ileride başka model eklemeye açık kalır.
- **Oturumdan ayrılma = tam otonom:** insan gömülü oturumdan `detach` edince iş onay beklemeden
  `queued` olur ve supervisor bir sonraki turu otomatik başlatır (`kind=resume`, istemde
  "insan oturumda şu değişiklikleri yaptı, devam et" notu). `awaiting_review`'a düşmez.
- Gözden geçirmeden plana alınanlar: G1, G2, G3, G4, G5, G6, G7, G8, G12–G18 (bkz. §14, G6 ayrıntısı §15).
- Token/bütçe sınırı **yok** (bilinçli karar).

---

## 1. Doğrulanmış zemin (bu makinede test edildi, 2026-10-29)
- `agy.exe` → `C:\Users\108097\AppData\Local\agy\bin\agy.exe`
- `agy -p "<istem>" --output-format json` →
  `{"conversation_id","status","response","duration_seconds","num_turns","usage{...}"}`
- `agy -p "<istem>" --conversation <ID>` → aynı sohbete devam eder; önceki turu **hatırladı** (num_turns 1→2).
- Diğer seçenekler: `--output-format stream-json`, `--input-format stream-json`, `--mode accept-edits|auto|plan`,
  `--dangerously-skip-permissions`, `--add-dir`, `--print-timeout`, `--json-schema`, `--model`, `--effort`,
  `--log-file`, `--agent`, `-i/--prompt-interactive`, `remote-control`.
- Python 3.14.6 + Textual 8.2.8 (`minion-cli-main/.venv`).
- (gözden geçirmede test edildi) `stream-json` biçimi: satır 1 `{"event":"init","conversation_id",...,"init":{cwd,tools,permission_mode}}`,
  ardından `step_update` (step_index, state, step_type, text_delta, usage), son `{"event":"result",...}`. **Kimlik ilk satırda.**
- `--conversation` farklı bir cwd'den çağrılınca da devam ediyor (worktree'den devam güvenli).
- `-p` modunda `ask_question` **yanıtsız geçiliyor ve `status` yine `SUCCESS`** → agy'nin status'u "iş bitti" demek değildir.
- agy'nin kendi araçları var: `ask_permission`, `send_message`, `manage_inbox`, `schedule`, `invoke_subagent`, `define_subagent`, `browser_*`.
- **Sınır:** Antigravity IDE'de açık olan pencerelere bağlanılamaz. Her iş = kimliği kayıtlı bir `agy` sohbeti.
  İnsan aynı sohbeti `agy --conversation <ID>` ile interaktif açabilir.

---

## 2. minion-cli-main analizi (U5)

| Bileşen | Dosya | Durum | Karar |
|---------|-------|-------|-------|
| Ajan daemon'u | `core/daemon.py` | **Sahte**: `random` ile ilerleme/CPU/maliyet, gerçek ajan yok | **ATILACAK**, yerine gerçek supervisor |
| Olay otobüsü | `core/event_bus.py` | Bellek içi asyncio kuyruğu + TCP 42010 yayını; **kalıcı değil** | Fikir korunur, yeniden yazılır (SQLite olay günlüğü + canlı yayın) |
| Durum | `core/state.py` | `RingBuffer` bellekte; kapanınca kaybolur; yalnız snapshot export | **ATILACAK**, yerine SQLite |
| Watchdog/heal | `daemon.py` | Kalp atışı simülasyonu | Fikir korunur → kira (lease) tabanlı gerçek kurtarma |
| Döşemeli çalışma alanı | `ui/workspace.py`, `drag_splitter.py`, `cli_tile.py` | **Gerçek, çalışıyor**, çok emek verilmiş | **TAŞINACAK** (izleme arayüzü olarak) |
| Gömülü terminal | `ui/panes/embedded_terminal.py` (winpty+pyte) | **Gerçek** ConPTY | **TAŞINACAK** → "ajan oturumunu panede aç" |
| agy kabuk panesi | `ui/panes/shell_pane.py` | agy'yi interaktif başlatıyor ama durum kaydı yok | Uyarlanacak: `--conversation <ID>` ile bağlanır |
| Hata/Sniper/Plugin panoları | `ui/panes/*` | Sahte veriyi gösteriyor | Gerçek olay akışına bağlanacak; Plugin Hub kaldırılır |
| Rapor export | `state.export_snapshot` | 100+ aynı içerikli rapor üretmiş | Kaldırılır; DB zaten kalıcı kayıt |

**Sonuç — evrilme değil, "çekirdek yeni, kabuk taşınır":**
- `agent_bus` yeni ve temiz bir depo olur. Çekirdek (bus + supervisor + CLI) sıfırdan, testli yazılır.
- TUI, F5'te `minion-cli-main/minion_fortress/ui` kodundan **kopyalanıp** `agent_bus/tui/` altına uyarlanır.
  (~6.2k satırın ≈ yarısı yeniden kullanılır.)
- `minion-cli-main` dokunulmadan kalır (referans/geri dönüş).
- Neden yerinde evrilmiyor: çekirdek sahte ve UI ile sıkı bağlı (UI doğrudan `FortressState`'e yazıyor);
  sahte kısmı söküp gerçek kalıcılığı eklemek, temiz çekirdeğe UI bağlamaktan daha riskli.

---

## 3. Mimari

```
                  ┌───────────────────────────────┐
                  │ ÜST YAPAY ZEKÂ (Claude Code)  │  ← plan yapar, iş böler, sonuç denetler, birleştirir
                  └──────────────┬────────────────┘
                                 │ `agentbus ...` CLI (ileride MCP aracı olarak da)
          ┌──────────────────────▼───────────────────────────┐
          │                AGENT BUS ÇEKİRDEĞİ               │
          │  bus.db (SQLite WAL)  = TEK DOĞRULUK KAYNAĞI      │
          │   jobs · turns · events · messages · board ·     │
          │   claims · agents · leases                       │
          │  runs/<job_id>/  = ham kayıtlar (append-only)     │
          └───────┬───────────────────────────┬──────────────┘
                  │                           │
     ┌────────────▼──────────┐       ┌────────▼─────────────┐
     │ SUPERVISOR (daemon)   │       │ İZLEME                │
     │ - zamanlayıcı (≤4)    │       │ agentbus watch (rich) │
     │ - agy turu çalıştırır │       │ agentbus tui (Textual,│
     │ - kira/kalp atışı     │       │  minion UI'dan)        │
     │ - çöküş kurtarma      │       └────────────────────────┘
     └────────────┬──────────┘
                  │ subprocess: agy -p ... --conversation <ID> --output-format stream-json
     ┌────────────▼──────────────────────────────────────┐
     │ agy ajanları (her biri kendi git worktree'sinde)   │
     │ ajanlar da `agentbus msg/board/claim` çağırabilir  │ ← ajanlar arası iletişim
     └───────────────────────────────────────────────────┘
```

### 3.1 Temel ilkeler
1. **Önce kaydet, sonra yap.** Her durum geçişi DB'ye işlenmeden yan etki (agy çağrısı, git işlemi) başlamaz.
2. **Tek doğruluk kaynağı = `bus.db`.** Dosyalar yalnız ham kayıt/artefakt; durum dosyadan çıkarılmaz.
3. **Yeniden oynatılabilir turlar.** Bir tur ya `completed` kaydıyla biter ya da yarım sayılır ve
   aynı `conversation_id` ile "kesildin, durumu kontrol et ve devam et" mesajıyla yeniden gönderilir.
4. **Kira (lease), PID değil.** Çalışan tur her 10 sn `lease_until`'i uzatır. Süresi geçen kira = ölü →
   supervisor işi `interrupted` yapar ve devralır. PID yeniden kullanımı/zombi sorunları yok.
5. **İdempotent komutlar.** `submit` istemci tarafı `idempotency_key` alır; aynı komut iki kez çalışsa da tek iş.
6. **Zaman UTC + `Z`.**
7. **Supervisor ölse bile CLI çalışır.** Okuma komutları DB'den; yazma komutları kuyruğa yazar, supervisor alır.

### 3.2 Neden SQLite (dosya kuyruğu değil)
- 4 paralel işçi + izleyici + üst ajan aynı anda okuyup yazacak → atomik işlem ve kilit şart.
- WAL modu: okuyucular yazıcıyı bloklamaz; `busy_timeout=5000`.
- Tek dosya, kurulum yok, yedeklemesi kolay. Ham çıktılar yine `runs/` altında okunabilir metin.
- **KOVAN dersi:** açık yazma işlemi içinde yavaş iş (log, ağ) yapma → kısa işlemler, yan etki dışarıda.

---

## 4. Veri modeli (`bus.db`, şema v1)

```sql
jobs(
  id TEXT PK,                 -- j_20261029_0001
  title TEXT, task_md TEXT,   -- görev metni (değişmez)
  parent_id TEXT NULL,        -- alt iş ise üst iş
  depends_on TEXT,            -- JSON liste: bu işler bitmeden başlama
  status TEXT,                -- aşağıdaki durum makinesi
  priority INT DEFAULT 5,
  agent_profile TEXT,         -- model/effort/mode ön ayarı
  conversation_id TEXT NULL,  -- agy sohbet kimliği (ilk turda yazılır)
  worktree_path TEXT, branch TEXT, base_commit TEXT,
  allowed_paths TEXT,         -- JSON glob listesi (sahiplik)
  attempt INT DEFAULT 0, max_attempts INT DEFAULT 3,
  lease_owner TEXT NULL, lease_until TEXT NULL,
  idempotency_key TEXT UNIQUE,
  created_at, updated_at, started_at, finished_at,
  result_summary TEXT, error TEXT
)
turns(
  id INTEGER PK, job_id, seq INT,           -- 1,2,3...
  kind TEXT,                                -- initial | followup | resume | review
  prompt TEXT, status TEXT,                 -- pending|running|completed|failed|interrupted
  response TEXT, usage_json TEXT, duration_s REAL,
  raw_path TEXT,                            -- runs/<job>/turns/003.stream.jsonl
  started_at, finished_at, UNIQUE(job_id, seq)
)
events(                                      -- append-only, izleme bunu kuyruk gibi okur
  id INTEGER PK, ts, job_id NULL, agent_id NULL,
  type TEXT,                                 -- job.created, turn.started, tool.call, file.changed, lease.lost, ...
  level TEXT, payload_json TEXT
)
messages(                                    -- ajan <-> ajan <-> üst ajan
  id INTEGER PK, ts, from_id, to_id,         -- to_id: job id | 'orchestrator' | 'all'
  body TEXT, read_at NULL, reply_to NULL
)
board(                                       -- ortak kara tahta: kararlar, arayüz sözleşmeleri
  key TEXT PK, value TEXT, author, updated_at, version INT
)
claims(                                      -- dosya sahiplik kilitleri
  path_glob TEXT, job_id, created_at, PRIMARY KEY(path_glob, job_id)
)
agents(                                      -- canlı işçi süreçleri (supervisor yuvaları)
  id TEXT PK, pid INT, host, started_at, heartbeat_at, current_job NULL
)
meta(key PK, value)                          -- schema_version, paused flag, max_parallel
```

### 4.1 İş durum makinesi
```
queued ──► blocked (depends_on bitmemiş) ──► queued
queued ──► running ──► awaiting_review ──► integrated ──► promoted   (§15)
                              │                └──► conflict | tests_failed ──► queued (düzeltme turu)
                              └──► rejected
              │  ├──► needs_input   (agy soru sordu / izin / belirsiz) ──► queued (cevap gelince)
              │  ├──► failed        (max_attempts aşıldı)
              │  ├──► human_attached(insan oturumu açtı; supervisor dokunmaz) ──► queued
              │  └──► interrupted   (kira düştü / süreç öldü) ──► queued (otomatik)
              └──► cancelled
paused  (global ya da iş bazlı; çalışan tur bitince durur)
```
Geçişler tek fonksiyondan (`transition(job, from, to, reason)`) yapılır; izinsiz geçiş hata verir
ve her geçiş `events`'e yazılır.

### 4.2 Diskteki ham kayıt
```
agent_bus_home/                       (varsayılan: %USERPROFILE%\.agent_bus  veya --home)
  bus.db  bus.db-wal
  runs/<job_id>/
    task.md
    turns/001.prompt.md  001.stream.jsonl  001.result.json
    agy.log
    diff.patch                     (iş bitince)
  worktrees/<job_id>/              (git worktree)
  logs/supervisor-YYYYMMDD.log
```

---

## 5. Bir turun yaşam döngüsü (kesintiye dayanıklılığın kalbi)
1. Supervisor bir yuva boşsa `queued` + bağımlılığı bitmiş en yüksek öncelikli işi **tek işlemde** alır:
   `status=running, lease_owner=<agent>, lease_until=now+60s, attempt+=1`.
2. Worktree yoksa oluşturur (`git worktree add worktrees/<id> -b agentbus/<id> <base>`), kaydeder.
3. `turns` satırı `pending` → istem `NNN.prompt.md`'ye yazılır → `running`.
4. Çağrı:
   `agy -p <istem> [--conversation <ID>] --model gemini-3.8-flash-high --output-format stream-json --dangerously-skip-permissions
    --add-dir <worktree> --log-file runs/<id>/agy.log --print-timeout <limit>` (cwd = worktree).
5. stream-json satırları **geldikçe** `NNN.stream.jsonl`'e eklenir ve önemli olanlar `events`'e
   (araç çağrısı, dosya yazımı) aktarılır → izleme canlı görür.
6. İlk satırda `conversation_id` görülür görülmez `jobs`'a yazılır (çökse bile sonraki tur devam edebilir).
7. Arka planda kalp atışı her 10 sn `lease_until`'i uzatır.
8. Bitiş: `result.json` yazılır → tur `completed` → yanıt çözümlenir (bkz. §6) → iş yeni duruma.
9. **Çöküş senaryoları:**
   | Ne oldu | Tespit | Kurtarma |
   |---|---|---|
   | Supervisor öldü / PC kapandı | açılışta `running` + kira süresi geçmiş | tur `interrupted`, iş `queued`, sonraki tur `kind=resume` |
   | agy süreci asılı | kira uzuyor ama çıktı yok > `stall_timeout` (vars. 10 dk) | süreci öldür, `interrupted` |
   | conversation_id yazılamadan öldü | `conversation_id IS NULL` | ilk tur baştan (worktree durumu korunur, istem "önceki deneme yarıda kaldı" notu içerir) |
   | Kota/429 | stderr/stream'de 429 | artan bekleme (30s,2m,8m), paralellik geçici 2 |
   | Disk/DB kilidi | `SQLITE_BUSY` | busy_timeout + kısa yeniden deneme |
10. Resume istemi şablonu: "Önceki adımın yarıda kesildi. `git status` ve son değişiklikleri kontrol et,
    tamamlanmamış işi bitir, tamamlanmışı tekrarlama. Bitince §6 formatında rapor ver."

---

## 6. Ajan sözleşmesi (agy'ye her işte verilen sistem talimatı)
- Çalışma dizini = kendi worktree'si; yalnız `allowed_paths` içine yaz.
- İş sonunda **son mesajı** şu JSON bloğuyla bitir (`--json-schema` ile zorlanır):
  ```json
  {"status":"done|needs_input|blocked|failed",
   "summary":"...", "files_changed":["..."], "tests":"...", "question":null}
  ```
- Ajanlar arası iletişim için CLI'yı kullanabilir:
  `agentbus msg send --to <job|orchestrator> "..."`, `agentbus msg inbox`,
  `agentbus board get/set <key>`, `agentbus claim <glob>`.
  (Ajan ortam değişkenleri: `AGENTBUS_HOME`, `AGENTBUS_JOB_ID` — kim olduğunu bilir.)
- `needs_input` dönerse soru `messages`'a `to=orchestrator` olarak düşer; üst ajan/insan
  `agentbus reply <job> "..."` ile yanıtlar → yeni `followup` turu.

---

## 7. CLI komut seti (`agentbus`)
```
agentbus init [--home DIR] [--repo PATH]         # DB + şema, hedef git repo kaydı
agentbus doctor                                   # agy, git, python, db, worktree sağlığı

# İşler
agentbus submit -t "başlık" -f task.md [--paths "src/a/**"] [--after j_..] [--priority 3]
                [--profile fast|deep] [--key IDEMP]
agentbus plan apply plan.yaml                     # üst ajanın çoklu iş planını tek seferde kuyruğa al
agentbus ls [--status running] [--json]
agentbus show <job> [--turns] [--events N]
agentbus send <job> "ek talimat"                  # aynı sohbete followup turu
agentbus reply <job> "cevap"                      # needs_input sorusuna yanıt
agentbus cancel|pause|resume <job>
agentbus retry <job>                              # failed → queued (attempt sıfırlanmaz, sınır artar)

# Supervisor
agentbus up [--parallel 4] [--detach]             # daemon başlat (tek örnek kilidi)
agentbus down                                     # nazik durdur: çalışan turlar bitince
agentbus recover                                  # elle kurtarma taraması (up zaten yapar)

# İzleme
agentbus watch                                    # canlı tablo (rich): işler, yuvalar, son olaylar
agentbus tail [--job J] [--type tool.call]        # olay akışı
agentbus tui                                      # Textual arayüz (F5)
agentbus stats                                    # token, süre, başarı oranı

# Oturumu açma (U8)
agentbus open <job> [--here]                      # iş human_attached olur; yeni konsolda
                                                  #  agy --conversation <ID> (cwd=worktree)
agentbus detach <job>                             # insan bitirdi → queued / awaiting_review

# Sonuç
agentbus diff <job>                               # worktree diff
agentbus review <job> [--approve|--reject "neden"]
agentbus merge <job>                              # iş → entegrasyon dalı (§15 Aşama 1)
agentbus promote <repo>                           # entegrasyon → main, yalnız güvenli ff (§15 Aşama 2)
agentbus revert <job>                             # birleştirmeyi geri al
agentbus gc [--older 7d]                          # birleşen worktree'leri temizle

# İletişim
agentbus msg send --to X "..."; agentbus msg inbox [--for X]
agentbus board get|set|ls
agentbus claim <glob> / unclaim
```
Tüm komutlarda `--json` (üst ajan için makine-okunur çıktı) ve anlamlı çıkış kodları.

---

## 8. Üst yapay zekâ (orkestratör) rolü (U1)
- **Kim:** Claude Code oturumu. Ayrı bir LLM daemon'u **yok** (maliyet + karmaşıklık); karar mercii Claude.
- **Akış:**
  1. Kullanıcı hedefi verir → Claude analiz eder → `plan.yaml` (işler, bağımlılıklar, `allowed_paths`, kabul kriteri).
  2. `agentbus plan apply plan.yaml` → kuyruk.
  3. `agentbus up --detach` + Claude `agentbus wait --any --json` (arka planda; bitince bildirim düşer, yoklama yok).
  4. Biten iş: Claude `diff`'i inceler, test çalıştırır → `review --approve` + `merge` ya da `send` ile düzeltme.
  5. `needs_input` mesajlarını yanıtlar veya kullanıcıya sorar.
- **Claude oturumu kesilirse:** hiçbir şey kaybolmaz; yeni oturumda `agentbus ls` + `msg inbox` ile toparlar.
- **Plan dosyası örneği:**
  ```yaml
  goal: "KOVAN Excel dışa aktarma"
  jobs:
    - key: api
      title: "Export API ucu"
      paths: ["backend/app/api/v1/export*.py"]
      task: |
        ...
      accept: ["pytest tests/test_export.py geçer"]
    - key: ui
      after: [api]
      paths: ["frontend/src/components/Export*"]
      task: ...
  ```
- **İleri (F7):** `agentbus mcp` — aynı komutları MCP araçları olarak sunar; Claude doğrudan araç çağırır.

---

## 9. İzleme / ortak durum (U6, U12)
- `watch`: üstte yuvalar (4), ortada iş tablosu (durum, tur, süre, token, son olay), altta olay akışı.
- `tui` = **ana komuta ekranı** (minion UI'dan; tüm ajanlar gömülü):
  ```
  ┌ AGENT BUS ─ supervisor: UP │ çalışan 3/4 │ kuyruk 5 │ token 412k │ 14:02Z ┐
  │ İŞLER            │ ┌ j_0007 api  RUNNING t3 ┐ ┌ j_0008 ui   RUNNING t1 ┐ │
  │ ● j_0007 api     │ │ > tool: edit export.py │ │ > reading Export.tsx   │ │
  │ ● j_0008 ui      │ │ > pytest ... 12 passed │ │ ...                    │ │
  │ ◐ j_0009 test    │ └────────────────────────┘ └────────────────────────┘ │
  │ ? j_0010 doc  ←soru│ ┌ j_0009 test BLOCKED ──┐ ┌ OLAYLAR / HATALAR ─────┐ │
  │ ✓ j_0005 promoted│ │ bekliyor: j_0007       │ │ 14:01 429 → bekleme 30s│ │
  │                  │ └────────────────────────┘ └────────────────────────┘ │
  │ agentbus> send j_0008 "tailwind kullan"  _                              │
  └─────────────────────────────────────────────────────────────────────────┘
  ```
  - Her çalışan iş otomatik bir döşemede açılır; döşeme o işin stream-json akışını canlı, okunur biçimde gösterir
    (araç çağrıları, dosya değişiklikleri, yanıt metni).
  - Döşemede **Enter / "bağlan"** → iş `human_attached` olur ve aynı döşeme içinde gerçek
    `agy --conversation <ID>` interaktif oturumu açılır (minion `embedded_terminal.py`, ConPTY).
    Çıkınca `detach` → iş supervisor'a döner. Yeni pencere isteyen için `open` korunur.
  - Alt satır = `agentbus` komut satırı (minion `cli_input.py`: tamamlama, geçmiş, yapıştırma).
  - Sol liste durum simgeleri; `?` = needs_input (soruyu göster + yanıtla).
  - Döşeme düzeni (minion `workspace.py` + `drag_splitter.py`) korunur; ≥5 iş olunca sekmeli/kaydırmalı.
  - TUI yalnız **görüntü + komut**: kapatılırsa ajanlar çalışmaya devam eder (supervisor ayrı süreç).
- Hata panosu = `level>=warn` olaylar.
- İzleyiciler DB'yi `events.id > son_id` ile 0.5 sn aralıkla okur (basit, kesintiye dayanıklı;
  soket gerekmez). Supervisor yokken bile çalışır.

---

## 10. Güvenlik ve sahiplik
- Tam otomatik izin (U9) → sınırlar: her iş ayrı worktree; `allowed_paths` dışında değişiklik =
  `awaiting_review` + uyarı (otomatik merge yok); birleştirme önce entegrasyon dalına, `main`'e yalnız
  güvenli fast-forward terfiyle (§15).
- Sırlar: `.env` vb. worktree'ye kopyalanmaz (git takip etmiyorsa zaten gelmez).
- `agentbus up` global tek-örnek kilidi (DB `meta.supervisor_lease`).

---

## 11. Depo yapısı
```
agent_bus/
  pyproject.toml           # paket: agentbus; giriş noktası `agentbus`
  README.md
  docs/PLAN.md  docs/protocol.md (ajan sözleşmesi)  docs/runbook.md (arıza rehberi)
  src/agentbus/
    __init__.py  __main__.py
    cli.py                 # argparse/typer komutları
    db.py                  # bağlantı, WAL, migrasyon, transaction yardımcıları
    models.py              # dataclass'lar + durum makinesi (transition)
    store/jobs.py turns.py events.py messages.py board.py claims.py
    supervisor.py          # zamanlayıcı, yuvalar, kira, kurtarma
    runner_agy.py          # tek tur: komut kurma, stream-json ayrıştırma
    worktree.py            # git worktree / diff / merge
    prompts.py             # sistem talimatı, resume şablonu, JSON şema
    watch.py               # rich canlı görünüm
    opener.py              # yeni konsolda agy --conversation açma
    mcp_server.py          # F7
    tui/                   # F5 — minion UI'dan taşınan
  tests/
    fake_agy.py            # sahte agy: senaryo dosyasına göre stream-json üretir, istenince asılır/çöker
    test_state_machine.py test_runner.py test_recovery.py test_cli.py test_worktree.py
  scripts/agentbus.cmd     # PATH kısayolu
```
Bağımlılıklar: `rich` (watch), `pyyaml` (plan), `textual`+`pywinpty`+`pyte` (yalnız F5, opsiyonel ek).

---

## 12. Fazlar ve kabul kriterleri
| Faz | İçerik | Kabul kriteri |
|-----|--------|---------------|
| **F0** Keşif | `stream-json` olay biçimini, `--json-schema` davranışını, `--print-timeout` ve çıkış kodlarını gerçek agy ile belgele (`docs/agy-protocol.md`) | Örnek akışlar kaydedildi; fake_agy bunlarla aynı biçimde |
| **F1** Çekirdek | db, şema, durum makinesi, store'lar, `init/submit/ls/show` | Birim testleri; geçersiz geçiş reddedilir |
| **F2** Runner + Supervisor | tek tur çalıştırma, kira, paralellik 4, 429 geri çekilme, `up/down/recover` | **K1**: fake_agy ortasında `taskkill /F` → `up` sonrası aynı conversation_id ile devam, tur kaybı yok. **K2**: 4 paralel iş biter. **K3**: DB hiçbir anda bozulmaz (1000 rastgele öldürme testi) |
| **F3** Worktree + inceleme | worktree oluştur/diff/merge/gc, allowed_paths denetimi | 2 iş aynı repoda çakışmadan; dış yola yazan iş merge'e gitmez |
| **F4** İletişim + açma | messages/board/claims, needs_input/reply, `open/detach` | Ajan A board'a yazar, ajan B okur (gerçek agy). `open` yeni konsolda aynı sohbeti açar ve iş human_attached olur |
| **F5** İzleme (zorunlu, U12) | `watch`, `tail`, `stats`; minion UI parçalarının `agentbus tui`ye taşınması: workspace/drag_splitter/cli_tile → iş döşemesi, embedded_terminal → gömülü agy oturumu, cli_input → komut satırı, theme | 4 paralel iş aynı ekranda canlı; döşemeden bağlan/ayrıl; TUI kapatılıp açılınca ajanlar kesintisiz, ekran DB'den aynen geri gelir |
| **F6** Orkestratör akışı | `plan apply`, `wait`, Claude için kullanım kılavuzu (CLAUDE.md parçası) | Gerçek uçtan uca: Claude 3 işlik plan → agy'ler → review → merge |
| **F7** MCP (opsiyonel) | `agentbus mcp` | Claude araç olarak submit/ls/send yapabilir |

Tahmini sıra: F0→F1→F2 (en kritik, en çok test) → F3 → F4 → F5 → F6 → F7.

---

## 13. Riskler
| Risk | Etki | Önlem |
|------|------|-------|
| agy stream-json biçimi belgesiz/değişebilir | ayrıştırma kırılır | F0'da kayıt; ayrıştırıcı bilinmeyen olayı yok sayar; son `result` satırı yeterli |
| agy kota/fiyat | paralel 4 pahalı | Bilinçli karar: token sınırı yok; `stats` ile izlenir, 429'da geri çekilme |
| Tam otomatik izin + komut çalıştırma | worktree dışına zarar | worktree + review kapısı; istenirse `--sandbox` profili |
| Windows yol/kodlama (Türkçe ad, MAX_PATH) | worktree hatası | kısa yol (`.agent_bus/wt/<kısa id>`), UTF-8 zorla |
| İnsan `open` ile oturumdayken supervisor da yazarsa | sohbet çatallanır | `human_attached` durumunda supervisor o işe tur göndermez |

---

## 14. Gözden geçirme — eksikler ve hatalar (2026-10-29)
Önem: 🔴 tasarım hatası (düzeltilmezse sistem yanlış çalışır) · 🟠 ciddi eksik · 🟡 iyileştirme

| # | Ön. | Sorun | Düzeltme (plana bağlayıcı) |
|---|-----|-------|---------------------------|
| G1 | 🔴 | **Yetim agy süreci → aynı sohbette iki ajan.** Supervisor ölünce çocuk `agy` yaşamaya devam eder; kira düşer, kurtarma ikinci bir `agy`'yi aynı `conversation_id` ve worktree ile başlatır → çatallanmış sohbet, çakışan yazımlar. | Her agy süreci bir **Windows Job Object**'e (`KILL_ON_JOB_CLOSE`) bağlanır; supervisor ölürse çocuklar da ölür. Ek olarak `turns.pid` + `process_create_time` saklanır; kurtarmadan önce süreç hâlâ canlıysa önce sonlandırılır. |
| G2 | 🔴 | **Uzun istem komut satırına sığmaz.** Windows komut satırı sınırı ~32 767 karakter; görev + sözleşme + bağlam bunu aşar, Türkçe karakter/tırnak kaçışı da kırılgan. | İstem **stdin'den** verilir (`--input-format stream-json --output-format stream-json`, tek NDJSON mesaj) ya da `-p` ile kısa "görev dosyasını oku: runs/<id>/task.md" yönlendirmesi. F0'da hangisinin çalıştığı doğrulanır. |
| G3 | 🔴 | **İnsan bağlıyken supervisor da yazabilir.** `open`/bağlan sırasında tur çalışıyorsa aynı sohbete iki istemci girer. | `attach` = önce iş `attach_pending`; çalışan tur bitince (ya da kullanıcı onayıyla kesilince) `human_attached`. Bu durumdaki işe supervisor tur göndermez; tek yazar kuralı DB'de koşullu güncellemeyle sağlanır. |
| G4 | 🔴 | **"SUCCESS" ≠ iş bitti** (test edildi). Soru araçları `-p`'de sessizce geçiliyor. | Durum yalnız §6 sonuç JSON'undan çıkarılır; JSON yoksa/geçersizse `needs_review`. Sistem talimatı: "soru sorma aracını kullanma; soruyu sonuç JSON'unda `needs_input` olarak dön". |
| G5 | 🟠 | **Worktree'de bağımlılık yok.** Yeni worktree'de `node_modules`, `venv`, `.env`, büyük yerel dosyalar bulunmaz → ajan test çalıştıramaz ya da 4 kez `npm install` yapar. | **Repo profili** (`repos/<ad>.yaml`): `setup` komutları, paylaşılacak klasörler (junction: `node_modules`, `venv`), kopyalanacak gizli dosyalar (açık izinle), test komutu. KOVAN için hazır profil. |
| G6 | 🟠 | **Birleştirme kullanıcının çalışma kopyasına dokunur.** `merge --into main` kullanıcının açık `main`'ini (ve KOVAN'daki eşzamanlı oturumları) bozabilir. | **İki aşamalı birleştirme** (ayrıntı §15): (1) iş dalı → hedef repo başına tek bir **entegrasyon worktree'si** (`.data/integration/<repo>`, dal `agentbus/integration`); sıralı (repo kilidi), testler orada koşar. (2) `main`'e **terfi** yalnız fast-forward ve yalnız güvenli koşullarda; aksi halde dokunmadan rapor. Kullanıcının çalışma kopyasında asla `checkout`/`reset`/`stash` yapılmaz. |
| G7 | 🟠 | **Paralel işlerde taban kayması / çakışma.** İşler aynı `base_commit`'ten başlar; biri birleşince diğerleri bayatlar. Repo kuralları (örn. KOVAN `sync_version.py --bump`) her işte çakışır. | Review öncesi otomatik `rebase` (çakışırsa iş `conflict` → ajana "rebase çöz" turu). Repo profiline `serialize_files` (VERSION gibi) → bu dosyalara yalnız entegrasyon adımı dokunur; ajanlara "sürüm artırma" yasak. |
| G8 | 🟠 | **Ajanlar otobüsü bozabilir.** Tam otomatik izinli ajan `agentbus cancel` ile başka işi iptal edebilir veya bus.db'yi elle düzenleyebilir. | Ajana verilen komut seti kapsamlı: `AGENTBUS_ROLE=agent` iken yalnız `msg/board/claim/report` ve yalnız kendi işi. `.data` klasörü ajan worktree'sinin dışında; sistem talimatında yazma yasağı; ihlal olayları denetlenir. |
| G12 | 🟡 | `allowed_paths` denetimi yalnız çalışma dizini diff'ine bakarsa ajanın yaptığı commit'ler kaçar. | Denetim `base_commit..HEAD` + çalışma ağacı birlikte. |
| G13 | 🟡 | Kodlama: Windows konsolu cp1254; agy çıktısı/ yol adları Türkçe. | Alt süreç `encoding="utf-8", errors="replace"`, `PYTHONUTF8=1`; DB'ye ham bayt değil metin. |
| G14 | 🟡 | `events` tablosu sınırsız büyür (her `text_delta` bir olay). | `text_delta`'lar yalnız `stream.jsonl`'e; DB'ye özet olaylar. Saklama: `gc --events 30d`. |
| G15 | 🟡 | `plan apply` yarıda kalırsa kısmi kuyruk. | Tek DB işlemi; her işin `idempotency_key` = `plan_hash:key`. |
| G16 | 🟡 | Ajanlar `agentbus`'ı PATH'te bulamayabilir (worktree, farklı venv). | `AGENTBUS_BIN` mutlak yol env ile verilir; talimatta tam komut yazılır. |
| G17 | 🟡 | Üst ajan (Claude) kapalıyken işler `awaiting_review`'da birikir; plan bunu söylemiyor. | Açıkça belgelenir; isteğe bağlı "otomatik onay" kuralı: testler geçti + allowed_paths temiz + diff < N satır → entegrasyon dalına otomatik. |
| G18 | 🟡 | `stall_timeout` 10 dk uzun derlemelerde yanlış-pozitif. | "Durgunluk" = son `step_update`'ten beri geçen süre (çıktı akmıyor), toplam süre değil; profile göre ayarlanır. |

**Faz etkisi:** G1, G2, G3, G4 → F2 kabul kriterine eklenir. G5, G6, G7 → F3'e. G8 → F4'e. G12–G18 ilgili fazlarda.

**Kapsam dışı bırakılanlar (kullanıcı kararı 2026-10-29):** G9 açılışta otomatik başlatma, G10 agy alt-ajan/zamanlama araçlarını kısıtlama, G11 bütçe sınırı (**bilinçli karar: token sınırı yok**; yalnız `agentbus stats` ile izlenir), G19 sahte agy ile test ayrımı. Numaralar boşluklu bırakıldı (karışmasın diye).

## 15. Güvenli birleştirme (G6 ayrıntısı)
Amaç: ajan çıktısı hedef repoya ulaşırken kullanıcının açık çalışma kopyası, açık dosyaları ve
eşzamanlı oturumlar **hiçbir koşulda** bozulmaz.

**Aşama 1 — entegrasyon (otomatik, güvenli):**
1. Hedef repo başına bir entegrasyon worktree'si: `.data/integration/<repo_id>/`, dal `agentbus/integration`.
   İlk kurulumda `main`'in o anki ucundan açılır.
2. Repo başına **tek kilit** (DB `meta.integration_lock:<repo_id>`): aynı anda tek birleştirme.
3. Sıra: entegrasyon dalını `main`'in güncel ucuna fast-forward et (main ilerlediyse) → iş dalını
   `rebase` et (G7) → `merge --no-ff` → repo profilindeki test komutu (G5) → `serialize_files` (VERSION vb.)
   burada güncellenir.
4. Herhangi bir adım başarısızsa: `git merge --abort` / `rebase --abort`, entegrasyon dalı **önceki
   commit'e geri** alınır (kendi worktree'si olduğu için güvenli), iş `conflict` veya `tests_failed` →
   ajana düzeltme turu. Kullanıcının reposu etkilenmez.
5. Her adım `events`'e; birleştirme öncesi/sonrası commit kimlikleri `jobs`'a yazılır (geri alma için).

**Aşama 2 — `main`'e terfi (`agentbus promote <repo>`):**
- Yalnız **fast-forward** (`main` entegrasyon dalının atası olmalı). Değilse önce Aşama 1 yeniden.
- `main` kullanıcının çalışma kopyasında **checkout edilmiş değilse:** `git update-ref` ile ilerletilir (çalışma ağacı yok, güvenli).
- `main` **checkout edilmişse:** yalnız çalışma ağacı tamamen temizse (`git status --porcelain` boş,
  devam eden merge/rebase yok) `git -C <repo> merge --ff-only agentbus/integration`. Kirli ise
  **dokunulmaz**; "terfi bekliyor: N commit, repo kirli" uyarısı + TUI rozeti. Kullanıcı hazır olunca tekrar dener.
- Asla: `checkout`, `reset --hard`, `stash`, `push --force`, `branch -f main`.
- Uzak sunucuya (`git push`) otomatik gönderim **yok**.
- Terfi tetikleyicisi: üst ajan (Claude) `review --approve` sonrası; tam otonom kipinde (G17 otomatik onay kuralı geçerse) otomatik.
- Geri alma: `agentbus revert <job>` → entegrasyon dalında `git revert -m 1 <merge_commit>`; terfi edilmişse yeniden terfi.

**Kabul kriterleri (F3'e eklenir):**
- K-G6a: kirli çalışma kopyalı repoda terfi denenir → hiçbir dosya değişmez, uyarı üretilir.
- K-G6b: çakışan iki iş → ikincisi `conflict`, entegrasyon dalı bozulmaz, birincisinin sonucu korunur.
- K-G6c: test kırılan birleştirme geri alınır; `main` hiç ilerlemez.
- K-G6d: birleştirme ortasında süreç öldürülür → yeniden başlatmada yarım merge temizlenir (abort), kilit kira ile düşer.

## 16. Açık sorular
- ~~Hedef repo~~ → iş başına. ~~Veri yeri~~ → `.data`. ~~TUI~~ → zorunlu ana ekran.
- ~~Model~~ → `gemini-3.8-flash-high`. ~~Detach davranışı~~ → tam otonom, otomatik `queued`.
- Açık soru kalmadı.
