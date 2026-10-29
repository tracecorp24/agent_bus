# İlerleme
Son güncelleme: 2026-10-29T11:55:00Z
Şu anki faz: F1 — Çekirdek (db, şema, durum makinesi, store'lar, CLI temeli)

## Fazlar
- [x] F0 — Keşif (agy protokolü, stream-json, stdin/schema/timeout testleri, fake_agy) (commit tamamlanıyor)
- [ ] F1 — Çekirdek (db, şema, durum makinesi, store'lar, CLI temeli)
- [ ] F2 — Runner + Supervisor (işçi döngüsü, kira, kurtarma, K1-K3)
- [ ] F3 — Worktree + İnceleme (git worktree, diff, iki aşamalı birleştirme, K-G6)
- [ ] F4 — İletişim + Açma (messages, board, claims, open/detach, agent kısıtları)
- [ ] F5 — İzleme (watch, tail, TUI Textual gömülü arayüz)
- [ ] F6 — Orkestratör akışı (plan apply, wait, uçtan uca senaryo)
- [ ] F7 — MCP (opsiyonel)

## Açık maddeler
- Yok

## Sonraki adım
F1 fazına geçmek: `src/agentbus/db.py`, `src/agentbus/models.py`, `src/agentbus/store/*` ve temel CLI komutlarını (`init`, `submit`, `ls`, `show`) geliştirmek.
