# İlerleme
Son güncelleme: 2026-10-29T13:27:00Z
Şu anki faz: F3 — Worktree + İnceleme (git worktree, diff, iki aşamalı birleştirme, K-G6)

## Fazlar
- [x] F0 — Keşif (agy protokolü, stream-json, stdin/schema/timeout testleri, fake_agy) (commit f577631)
- [x] F1 — Çekirdek (db, şema, durum makinesi, store'lar, CLI temeli) (commit 59df4dd)
- [x] F2 — Runner + Supervisor (işçi döngüsü, kira, kurtarma, K1-K3) (commit tamamlanıyor)
- [ ] F3 — Worktree + İnceleme (git worktree, diff, iki aşamalı birleştirme, K-G6)
- [ ] F4 — İletişim + Açma (messages, board, claims, open/detach, agent kısıtları)
- [ ] F5 — İzleme (watch, tail, TUI Textual gömülü arayüz)
- [ ] F6 — Orkestratör akışı (plan apply, wait, uçtan uca senaryo)
- [ ] F7 — MCP (opsiyonel)

## Açık maddeler
- Yok

## Sonraki adım
F3 fazına geçmek: `src/agentbus/worktree.py` (git worktree oluştur/kaldır, diff alma, allowed_paths G12 denetimi), iki aşamalı güvenli birleştirme (§15 / G6 / G7 rebase, Aşama 1 entegrasyon worktree'si, Aşama 2 yalnız fast-forward terfi) ve K-G6a..d testleri.
