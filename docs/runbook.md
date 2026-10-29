# AGENT BUS — İşletim ve Arıza Giderme Rehberi (Runbook)

Bu belge, **AGENT BUS** sisteminin günlük işletimi, acil durum müdahaleleri, süreç kurtarma ve yaygın sorunların çözüm adımlarını içerir.

---

## 1. Mimari Genel Bakış ve Temel Prensipler

- **Tek Kayıt Kaynağı (Single Source of Truth):** `.data/bus.db` (SQLite WAL modu).
- **Süreç İzolasyonu:** Her `agy` ajanı bağımsız bir Windows Job Object (`KILL_ON_JOB_CLOSE`) ve izole Git Worktree altında çalışır.
- **Kira ve Kalp Atışı:** Supervisor ve çalışan ajanlar periyodik olarak veritabanındaki kira sürelerini günceller.
- **Güvenli Birleştirme (§15):** Çalışma ağacına hiçbir zaman yıkıcı komut uygulanmaz. İki aşamalı güvenli birleştirme (Entegrasyon Dalı -> Test -> Hızlı İleri Terfi) kullanılır.

---

## 2. Acil Durum Senaryoları ve Çözüm Adımları

### 2.1. Supervisor veya Ajan Süreci Asılı Kaldı / Çöktü

**Belirtiler:**
- İş `running` durumunda kalmış fakat CPU/IO etkinliği yok.
- `agentbus show <job_id>` çıktısında `lease_until` süresi geçmiş.

**Çözüm:**
1. Otomatik Kurtarma Komutunu Çalıştırın:
   ```cmd
   run.bat recover
   ```
2. Supervisor'ı Yeniden Başlatın:
   ```cmd
   run.bat up
   ```
   *Not: Supervisor başlangıçta otomatik olarak `recover()` çalıştırır. Windows Job Object ve PID/oluşturma zamanı kontrolü sayesinde yetim kalan süreçler güvenle sonlandırılır ve yarım kalan işler aynı `conversation_id` ile kaldığı yerden devam eder.*

---

### 2.2. Manuel Süreç Temizliği (Windows Görev Yöneticisi / PowerShell)

Otomatik kurtarma mekanizmasının ötesinde bir acil durum gerektiğinde:
```powershell
# Yetim kalmış agy süreçlerini tespit et
Get-Process -Name agy -ErrorAction SilentlyContinue

# Yetim git süreçlerini temizle
Get-Process -Name git -ErrorAction SilentlyContinue | Stop-Process -Force
```

---

### 2.3. Entegrasyon Çakışması (Conflict) ve Güvenli Geri Alma

**Belirtiler:**
- `agentbus merge <job_id>` hata verir veya iş `conflict` durumuna geçer.
- Hedef depodaki diğer dallarla çakışma yaşanmıştır.

**Çözüm:**
1. İşi reddedin ve gerekçeyi iletin:
   ```cmd
   run.bat review <job_id> --reject --reason "main dalı ile çakışma var, lütfen rebase yapın"
   ```
2. İş yeniden kuyruğa alınır ve ajan bir sonraki turda rebase talimatı alarak çakışmayı çözer.
3. İşi tamamen iptal etmek veya geri almak gerekirse:
   ```cmd
   run.bat revert <job_id>
   ```

---

### 2.4. Entegrasyon Test Başarısızlığı (tests_failed)

**Belirtiler:**
- İş birleştirme testi çalıştırdıktan sonra `tests_failed` durumuna düşer.

**Çözüm:**
- İki aşamalı entegrasyon protokolü gereği, testler başarısız olduğunda entegrasyon dalı otomatik olarak geri alınır (`git reset --hard` entegrasyon dalında yapılır, kullanıcının `main` dalına veya çalışma dizinine ASLA dokunulmaz).
- Gerekli hata mesajı `jobs.error` alanına yazılır.
- Düzeltme turu başlatmak için:
  ```cmd
  run.bat review <job_id> --reject --reason "Birim testler başarısız oldu: test_api.py hata verdi"
  ```

---

### 2.5. Model Kotası / 429 RESOURCE_EXHAUSTED Hatası

**Belirtiler:**
- `agy` çıktısında `429 Quota exceeded` hatası.
- İş `interrupted` durumuna geçip üstel geri çekilme (exponential backoff) bekler.

**Çözüm:**
1. Sistem otomatik olarak 5s, 10s, 20s, 40s üstel bekleme uygular.
2. Bekleme süresini manuel sıfırlayıp kuyruğa almak için:
   ```cmd
   run.bat retry <job_id>
   ```

---

### 2.6. Yetim Worktree ve Disk Temizliği

**Belirtiler:**
- `.data/worktrees/` altında tamamlanmış veya iptal edilmiş işlere ait dizinler kalmış.

**Çözüm:**
Sistemin çöp toplayıcısını (GC) çalıştırın:
```cmd
run.bat gc
```
*Bu komut, durumu `promoted`, `cancelled` veya `rejected` olan işlerin worktree dizinlerini güvenle temizler ve git worktree referanslarını budar (`git worktree prune`).*

---

## 3. Sistem Sağlık Kontrolü (Doctor)

Sistemin ortam, git, python ve agy bağımlılıklarını doğrulamak için:
```cmd
run.bat doctor
```

Çıktıda tüm bileşenlerin `[OK]` yeşil yandığını doğrulayın:
- Python sürümü: 3.14+
- SQLite WAL: Aktif
- Windows Job Object: Destekleniyor
- Git CLI: Erişilebilir
- UTF-8 Kodlaması: Aktif
