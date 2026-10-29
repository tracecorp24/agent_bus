# AGENT BUS

**AGENT BUS**, Claude Code (üst yapay zekâ) orkestratörlüğünde birden fazla Antigravity (`agy`) ajanını kalıcı bir SQLite WAL otobüsü, izole Git Worktree'leri ve gömülü terminal arayüzü (TUI) üzerinden yöneten dayanıklı bir çoklu ajan çalışma alanıdır.

---

## 🚀 Öne Çıkan Özellikler

1. **Sıfır Kurulum (Zero Setup):** Tüm bağımlılıklar ve sanal ortam (`.venv`) proje klasörü içinde önceden derlenmiş ve paketlenmiştir. Kullanıcının herhangi bir paket veya araç kurması gerekmez.
2. **Kesintiye Dayanıklılık (Crash Recovery):** Windows Job Objects (`KILL_ON_JOB_CLOSE`) ve PID / oluşturma zamanı doğrulaması ile yetim süreç bırakmaz. Kesilen oturumlar aynı `conversation_id` ile kaldığı yerden devam eder.
3. **Güvenli İki Aşamalı Birleştirme (§15):** Kullanıcının çalışma kopyasına veya hedef repolara asla yıkıcı git komutu uygulanmaz. Değişiklikler izole entegrasyon worktree'sinde birleştirilir, test edilir ve yalnızca başarılı olursa ana dala hızlı ileri (`fast-forward`) terfi edilir.
4. **Çoklu Ajan İletişimi ve Pano:** Ajanlar arası doğrudan mesajlaşma (`msg send / inbox`) ve ortak anahtar-değer durumu (`board`).
5. **Gömülü Çoklu Terminal Arayüzü (TUI):** Textual ve Windows ConPTY tabanlı, tüm ajanların çıktılarını canlı izleme ve gerektiğinde insan müdahalesi (`human_attached`) sağlama imkanı.

---

## 🛠️ Hızlı Başlangıç

Proje kök dizinindeki `run.bat` veya `agentbus.bat` komut dosyası ile hemen çalıştırabilirsiniz:

```cmd
:: Sistem sağlık kontrolü
run.bat doctor

:: Veritabanını ilklendir
run.bat init

:: Supervisor arka plan servisini başlat
run.bat up --daemon

:: Canlı TUI panosunu aç
run.bat tui
```

---

## 📋 CLI Komut Referansı

| Komut Grubu | Komut | Açıklama |
|---|---|---|
| **Sistem & Tanı** | `run.bat doctor` | Python, SQLite WAL, Git ve agy ortamını doğrular |
| | `run.bat init` | `.data/bus.db` veritabanını ve şemayı hazırlar |
| **Daemon (Supervisor)**| `run.bat up` | Zamanlayıcıyı başlatır (en çok 4 paralel iş) |
| | `run.bat down` | Supervisor servisini nazikçe durdurur |
| | `run.bat recover` | Yetim süreçleri öldürür ve süresi dolmuş işleri kurtarır |
| | `run.bat pause / resume` | İş alımını duraklatır veya devam ettirir |
| **İş & Plan Yönetimi** | `run.bat submit "<title>" -t "<task>"` | Yeni bir iş kuyruğa ekler |
| | `run.bat plan apply <file.yaml>` | Çok işli planı atomik ve idempotant olarak uygular |
| | `run.bat ls [--status <st>]` | İşleri listeler (kuyruk, çalışan, inceleme bekleyen) |
| | `run.bat show <job_id>` | İşin detaylarını, turlarını ve durumunu gösterir |
| | `run.bat wait <job_id>` | İş tamamlanana kadar bloklar |
| | `run.bat cancel <job_id>` | İşi iptal eder |
| | `run.bat retry <job_id>` | Başarısız işi sıfırlayıp kuyruğa alır |
| **Git & Güvenli Entegrasyon**| `run.bat diff <job_id>` | İşin worktree'sindeki değişiklik farkını gösterir |
| | `run.bat review <job_id>` | İşi onaylar veya reddederek düzeltme turu açar |
| | `run.bat merge <job_id>` | Aşama 1: İşi entegrasyon dalında birleştirir |
| | `run.bat promote [repo]` | Aşama 2: Entegrasyon dalını hedef repoya terfi eder |
| | `run.bat revert <job_id>` | Birleştirilmiş bir işi geri alır |
| | `run.bat gc` | Tamamlanmış işlerin worktree dizinlerini temizler |
| **İletişim & Pano** | `run.bat msg send <to> "<body>"` | Ajanlar veya orkestratör arası mesaj gönderir |
| | `run.bat msg inbox` | Okunmamış veya tüm mesajları listeler |
| | `run.bat board set <k> <v>` | Paylaşımlı panoya anahtar-değer yazar |
| | `run.bat board get <k>` | Panodan veri okur |
| | `run.bat claim / unclaim <res>`| Ortak kaynaklar üzerinde kilit alır/bırakır |
| **İzleme & Arayüz** | `run.bat watch` | Rich tabanlı konsol canlı durum tablosu |
| | `run.bat tail <job_id> [-f]` | İşin agy akışını canlı takip eder |
| | `run.bat tui` | Textual gömülü terminal arayüzünü açar |
| **İnsan Müdahalesi** | `run.bat open <job_id>` | İşe insan terminal oturumu bağlar |
| | `run.bat detach <job_id>` | İşi otonom çalışmaya geri döndürür |

---

## 🖥️ Textual TUI Panosu

`run.bat tui` komutu ile başlatılır:
- **Sol Panel:** Tüm işlerin canlı durum listesi (Queued, Running, Awaiting Review vb.).
- **Sağ Üst Panel:** Çalışan ajanların ConPTY destekli gerçek zamanlı terminal döşemeleri.
- **Sağ Alt Panel:** Olay günlüğü (Event stream) ve etkileşimli komut istemi.
- **Klavye Kısayolları:**
  - `q` : Çıkış
  - `Tab` / `Shift+Tab` : Paneller arası odak geçişi
  - `Ctrl+O` : Seçili işe insan oturumu bağla (`open`)
  - `Ctrl+D` : İnsan oturumundan ayrıl (`detach`)

---

## 🛡️ Güvenlik ve İzolasyon Sözleşmesi

- `AGENTBUS_ROLE=agent` ortam değişkeniyle çalışan alt ajanlar sistem komutlarını çalıştıramaz. Yalnızca `msg`, `board`, `claim`, `unclaim` ve kendi `show` komutlarını kullanabilir (Yetkisiz çağrılar Çıkış Kodu 13 ile engellenir).
- `allowed_paths` koruması ile ajanların yalnızca belirlenen dizin modellerinde dosya değiştirmesi denetlenir (G12).

---

## 📚 Dokümantasyon

- **Mimari ve Tasarım Planı:** [docs/PLAN.md](docs/PLAN.md)
- **İşletim ve Arıza Giderme Rehberi:** [docs/runbook.md](docs/runbook.md)
- **Doğrulanmış Agy Protokolü:** [docs/agy-protocol.md](docs/agy-protocol.md)
- **Mimari Kararlar ve Varsayımlar:** [docs/KARARLAR.md](docs/KARARLAR.md)
- **Faz Geliştirme İlerleme Kaydı:** [docs/ILERLEME.md](docs/ILERLEME.md)
