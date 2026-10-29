# Kararlar ve Varsayımlar

Bu dosya, `docs/PLAN.md` ve `UYGULAMA_PROMPTU.md` belgelerinde belirtilmeyen veya netleştirilmesi gereken varsayımları ve kararları belgeler.

## Sabit Kararlar (Prompt & Plan)
- Model: `gemini-3.8-flash-high`
- İzinler: `--dangerously-skip-permissions`
- Paralellik: en çok 4 paralel iş
- İzolasyon: iş başına git worktree
- Veri konumu: `agent_bus/.data/` (bus.db, runs, worktrees)
- Token sınırı: Yok
- Detach sonrası: iş otomatik devam eder (`queued`, kind=resume)
- Gözden geçirme: G1–G8, G12–G18 uygulanır; G9, G10, G11, G19 uygulanmaz.
- Güvenli birleştirme (§15): Kullanıcının çalışma kopyasına asla dokunulmaz.

## Varsayımlar
- (Varsayım 1): Python paket kurulumu pyproject.toml ile hatchling veya flit/setuptools kullanılabilir. Standard `setuptools` veya `flit_core` sade bir kurulum için tercih edilecektir.
