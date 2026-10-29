# Görev: AGENT BUS projesini plana göre uygula

## Bağlam
`C:\Users\108097\Desktop\agent_bus\` klasöründe **AGENT BUS** adlı bir proje kuracaksın. Amaç şu:
Claude Code (üst yapay zekâ) CLI üzerinden birden fazla Antigravity (`agy`) ajanını, kalıcı bir
SQLite otobüsüyle yönetecek. Sistem kesintiye dayanıklı olacak, ortak durum izlenecek ve tüm ajanlar
tek bir terminal arayüzünde gömülü görünecek.

**Tek bağlayıcı kaynak:** `C:\Users\108097\Desktop\agent_bus\docs\PLAN.md`
İşe başlamadan önce bu dosyayı **baştan sona oku**. Özellikle şu bölümler önemli:
§0 istekler ve kararlar, §1 doğrulanmış agy davranışı, §4 veri modeli, §5 tur yaşam döngüsü,
§6 ajan sözleşmesi, §7 CLI, §12 fazlar ve kabul kriterleri, §14 gözden geçirme maddeleri, §15 güvenli birleştirme.
Plan ile bu prompt çelişirse **plan geçerlidir**. Planda olmayan bir kararı kendin uydurma;
`docs/KARARLAR.md`'ye "varsayım" diye yaz ve en sade seçeneği uygula.

## Kesin kurallar
1. **Tüm kod `C:\Users\108097\Desktop\agent_bus\` altında olacak.** Başka yere dosya yazma.
2. **`C:\Users\108097\Desktop\minion-cli-main\` salt okunurdur.** Oradan yalnızca §2'de "TAŞINACAK" denen
   UI dosyalarını **kopyala**: `ui/workspace.py`, `drag_splitter.py`, `cli_tile.py`, `cli_input.py`,
   `theme.py`, `panes/embedded_terminal.py`, `panes/shell_pane.py`. Kopyaları `src/agentbus/tui/` altında uyarla.
   Sahte çekirdeği (`core/daemon.py`, `state.py`, `event_bus.py`) taşıma.
3. **Sabit kararlar:**
   - model `gemini-3.8-flash-high`
   - `--dangerously-skip-permissions`
   - her iş kendi git worktree'sinde, en çok 4 paralel iş
   - veri `agent_bus\.data\` altında (`.gitignore`'da)
   - token sınırı **yok**
   - detach sonrası iş otomatik devam eder
   - §14'te alınanlar G1–G8 ve G12–G18; **G9, G10, G11, G19 uygulanmaz**
4. **Birleştirme (§15) hiçbir koşulda kullanıcının çalışma kopyasını bozmaz.** Hedef repolarda `checkout`,
   `reset --hard`, `stash`, `push --force`, `branch -f main` ve otomatik `git push` **yasak**.
   Testleri yalnızca `.data` altında oluşturduğun geçici test repolarında çalıştır.
   **KOVAN veya başka bir gerçek repo üzerinde deneme yapma.**
5. **Gerçek `agy` çağrıları para ve kota harcar.** Bu yüzden gerçek `agy` testleri kısa istemli olmalı,
   pytest'te `-m live` ile işaretlenmeli ve sayıca az tutulmalı. Diğer tüm testler `tests/fake_agy.py` ile çalışır.
   `fake_agy.py`, §1'deki gerçek stream-json biçimini birebir üretmeli; asılma ve çökme senaryolarını da desteklemeli.
6. **Ortam:** Windows 11, PowerShell ve Git Bash.
   - Python 3.14 kullan: `C:\Users\108097\Desktop\minion-cli-main\.venv\Scripts\python.exe` (`venv` oluşturmak için taban olarak da kullanılabilir).
   - Projenin kendi `.venv`'ini `agent_bus\.venv` altına kur.
   - `pyproject.toml` ile kur, giriş noktası `agentbus` olsun.
   - Her yerde UTF-8 kullan (G13).
   - PowerShell `Set-Content` ile dosya yeniden yazma, kodlamayı bozar.
7. **Kod ve yorumlar Türkçe, sade olsun.** Zaman damgaları UTC olsun, sonunda `Z` bulunsun.
   Durum geçişleri yalnızca tek bir `transition()` fonksiyonundan yapılsın.

## Çalışma sırası
`F0 → F1 → F2 → F3 → F4 → F5 → F6` (F7/MCP opsiyonel, en son, ancak süre kalırsa).
Her faz için:
1. Planın o fazla ilgili bölümünü ve faza bağlanan §14 maddelerini tekrar oku.
2. Uygula.
3. Kabul kriterlerini **test olarak** yaz ve çalıştır: `.venv\Scripts\python -m pytest -m "not live"`.
4. Faz bir gerçek agy davranışına dayanıyorsa 1–2 kısa `live` testi çalıştır.
5. `git init` ilk fazda yapılır. Her faz sonunda commit at: `feat(F<n>): ...`.
6. `docs/ILERLEME.md`'yi güncelle (format aşağıda).

Bir fazın kabul kriteri geçmeden sonraki faza **geçme**. Bir kriter 3 denemede geçmiyorsa
`ILERLEME.md`'ye nedenini yaz, o maddeyi "AÇIK" işaretle, faz içinde bağımsız işlere devam et.

### Faz notları
- **F0:** Gerçek agy ile şunları kaydet: stream-json çıktısının tam örnekleri, `--input-format stream-json` ile
  stdin'den istem verilip verilemediği (G2), `--json-schema` davranışı, `--print-timeout` aşımı ve çıkış kodları,
  hata/429 çıktısı. Bunları `docs/agy-protocol.md`'ye yaz, ham örnekleri `tests/fixtures/`'a koy.
  G2 için hangi yöntemin çalıştığı burada kesinleşir.
- **F2 (en kritik):** G1 (Windows Job Object ile çocuk süreç bağlama + PID/oluşturma zamanı kontrolü),
  G3 (tek yazar), G4 (durum yalnız sonuç JSON'undan), kira/kalp atışı, 429 geri çekilme.
  K1 testi şunu doğrulamalı: süreç gerçekten `taskkill /F` ile öldürülür, ardından `agentbus up`
  aynı `conversation_id` ile devam eder ve hiçbir tur kaydı kaybolmaz.
- **F3:** G5 repo profilleri (KOVAN profili için `node_modules`/`venv` junction tanımı yaz ama KOVAN'da çalıştırma),
  G6/§15 iki aşamalı birleştirme ve K-G6a..d testleri, G7 rebase.
- **F5:** TUI ana ekrandır (U12). TUI kapatılıp açıldığında durum DB'den aynen geri gelmeli.
  Ajanlar TUI'den bağımsız çalışmalı.

## Kendi kesintine karşı dayanıklılık
Bu uzun bir iş; oturumun yarıda kesilebilir. Bu yüzden:
- **Her alt adımdan sonra** `docs/ILERLEME.md`'yi güncelle. Bu dosya senin kaldığın yeri gösteren tek kaynaktır.
- Yeni bir oturumda **önce** `ILERLEME.md`'yi ve `git log`'u oku, sonra kaldığın yerden devam et.
  Yapılmış işi tekrar yapma.
- Küçük ve sık commit at; yarım iş commit'lenmesin, gerekirse `wip:` önekiyle commit'le.

`ILERLEME.md` formatı:
```
# İlerleme
Son güncelleme: <UTC Z>
Şu anki faz: F<n> — <alt adım>
## Fazlar
- [x] F0 — <özet> (commit <hash>)
- [ ] F1 — ...
## Açık maddeler
- <madde> — <neden> — <denenenler>
## Sonraki adım
<tek cümle, yeni oturum ne yapacağını buradan bilsin>
```

## Bitirme ölçütü
F0–F6 kabul kriterlerinin hepsi geçtiğinde iş biter. Son olarak:
- `pytest -m "not live"` tamamen yeşil olmalı.
- §12 F6 senaryosu bir kez gerçek agy ile koşulmalı: geçici test reposunda 3 işlik plan, agy ajanları, review, entegrasyon ve terfi.
- `README.md`'ye kurulum, `agentbus` komutları, TUI kullanımı ve arıza rehberi (`docs/runbook.md`) yazılmalı.

Son raporunda şunlar olsun: hangi fazlar tamam, test sonuçları (geçen/kalan sayısı), açık kalan maddeler ve nedenleri,
plandan sapılan yerler (`KARARLAR.md`'ye referansla).
