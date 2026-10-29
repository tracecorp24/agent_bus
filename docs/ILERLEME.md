# İlerleme
Son güncelleme: 2026-10-29T14:17:00Z
Şu anki faz: F4 — İletişim + Açma (messages, board, claims, open/detach, agent kısıtları)

## Fazlar
- [x] F0 — Keşif (agy protokolü, stream-json, stdin/schema/timeout testleri, fake_agy) (commit f577631)
- [x] F1 — Çekirdek (db, şema, durum makinesi, store'lar, CLI temeli) (commit 59df4dd)
- [x] F2 — Runner + Supervisor (işçi döngüsü, kira, kurtarma, K1-K3) (commit ec9569b)
- [x] F3 — Worktree + İnceleme (git worktree, diff, iki aşamalı birleştirme, K-G6) (commit 8dba8bc)
- [ ] F4 — İletişim + Açma (messages, board, claims, open/detach, agent kısıtları)
- [ ] F5 — İzleme (watch, tail, TUI Textual gömülü arayüz)
- [ ] F6 — Orkestratör akışı (plan apply, wait, uçtan uca senaryo)
- [ ] F7 — MCP (opsiyonel)

## Açık maddeler
- Yok

## Sonraki adım
F4 fazını uygulamak: Ajanlar arası iletişim (`msg send`, `msg inbox`), ortak tahta (`board get/set/ls`), dosya sahipliği (`claim`/`unclaim`), etkileşimli insan devralması (`open`/`detach`) ve ajan CLI kısıtları (`AGENTBUS_ROLE=agent`).
