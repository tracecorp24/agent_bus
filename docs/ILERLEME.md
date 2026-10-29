# İlerleme
Son güncelleme: 2026-10-29T12:13:00Z
Şu anki faz: F2 — Runner + Supervisor (işçi döngüsü, kira, kurtarma, K1-K3)

## Fazlar
- [x] F0 — Keşif (agy protokolü, stream-json, stdin/schema/timeout testleri, fake_agy) (commit f577631)
- [x] F1 — Çekirdek (db, şema, durum makinesi, store'lar, CLI temeli) (commit tamamlanıyor)
- [ ] F2 — Runner + Supervisor (işçi döngüsü, kira, kurtarma, K1-K3)
- [ ] F3 — Worktree + İnceleme (git worktree, diff, iki aşamalı birleştirme, K-G6)
- [ ] F4 — İletişim + Açma (messages, board, claims, open/detach, agent kısıtları)
- [ ] F5 — İzleme (watch, tail, TUI Textual gömülü arayüz)
- [ ] F6 — Orkestratör akışı (plan apply, wait, uçtan uca senaryo)
- [ ] F7 — MCP (opsiyonel)

## Açık maddeler
- Yok

## Sonraki adım
F2 fazına geçmek: `src/agentbus/runner_agy.py` (tek tur çalıştırma, G1 Windows Job Object, G2 stdin besleme, G4 sonuç JSON ayrıştırma), `src/agentbus/supervisor.py` (paralellik 4, kalp atışı/kira yenileme, 429 geri çekilme, çöküş kurtarma) ve K1-K3 kabul testlerini yazmak.
