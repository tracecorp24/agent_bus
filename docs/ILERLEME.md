# İlerleme
Son güncelleme: 2026-10-30T06:17:00Z
Şu anki faz: TAMAMLANDI (F0 — F6 tüm kabul kriterleri ve Gelişmiş TUI çoklu terminal paneli tamamlandı)

## Fazlar
- [x] F0 — Keşif (agy protokolü, stream-json, stdin/schema/timeout testleri, fake_agy) (commit f577631)
- [x] F1 — Çekirdek (db, şema, durum makinesi, store'lar, CLI temeli) (commit 59df4dd)
- [x] F2 — Runner + Supervisor (işçi döngüsü, kira, kurtarma, K1-K3) (commit ec9569b)
- [x] F3 — Worktree + İnceleme (git worktree, diff, iki aşamalı birleştirme, K-G6) (commit 8dba8bc)
- [x] F4 — İletişim + Açma (messages, board, claims, open/detach, agent kısıtları) (commit 2733eb1)
- [x] F5 — İzleme (watch, tail, Textual ConPTY dinamik çoklu terminal tuvali, DragSplitter, 4 seçenekli yeni pencere sihirbazı)
- [x] F6 — Orkestratör akışı (plan apply, wait, 3 işlik uçtan uca senaryo ve terfi) (commit 17e1185)
- [ ] F7 — MCP (opsiyonel)

## Kabul Testi Durumu
- `pytest -m "not live"`: 43 testin 43'ü geçti (%100 BAŞARI)
- F2 K1 (Süreç kesme ve kesintisiz kurtarma): GEÇTİ
- F2 K2 (4 paralel işçi eşzamanlı çalışma): GEÇTİ
- F2 K3 (Veritabanı bütünlüğü ve tek yazar kilidi): GEÇTİ
- F3 K-G6a (Kirli çalışma ağacı koruması): GEÇTİ
- F3 K-G6b (Entegrasyon çakışma izolasyonu): GEÇTİ
- F3 K-G6c (Test hatasında güvenli geri alma): GEÇTİ
- F3 K-G6d (Bayat kilit kurtarma ve revert): GEÇTİ
- F4 İletişim & Pano (Mesajlaşma, claim, role=agent kısıtları): GEÇTİ
- F5 İzleme & TUI (Watch, tail, Dinamik ConPTY terminali, DragSplitter, Presets): GEÇTİ
- F6 Orkestrasyon (G15 atomik ve idempotant plan apply, 3 işlik bağımlılık zinciri terfisi): GEÇTİ

## Açık maddeler
- Yok. Kullanıcı tarafından talep edilen tüm arayüz, ConPTY çoklu terminal ve çalışma mimarisi eksiksiz tamamlandı.

## Sonraki adım
Kodları GitHub deposuna (`https://github.com/tracecorp24/agent_bus`) commit ve pushlamak.
