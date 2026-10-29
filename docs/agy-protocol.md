# Antigravity (agy) Protokolü ve Canlı Davranış Raporu (F0)

Bu belge, `agy` v1.4.10 üzerinde 2026-10-29 tarihinde yapılan canlı keşif testlerinin sonuçlarını ve AGENT BUS projesine bağlayıcı sözleşmeyi içerir.

## 1. Olay Akışı Biçimi (`--output-format stream-json`)

`agy` her satırda tek bir JSON nesnesi (NDJSON) üretir. Akış şu üç ana olay tipinden oluşur:

### 1.1 `init` Olayı (Her zaman 1. satır)
Sohbet oturumu başlar başlamaz üretilir. `conversation_id` ilk bu satırdan okunur.
```json
{
  "event": "init",
  "conversation_id": "864b8f93-16e0-4693-8e49-2487dfba0559",
  "init": {
    "model": "gemini-3.8-flash-high",
    "cwd": "C:\\Users\\108097\\Desktop\\agent_bus",
    "tools": ["run_command", "read_file", "write_to_file", "finish", "..."],
    "permission_mode": "always-proceed",
    "json_schema": { ... }
  }
}
```

### 1.2 `step_update` Olayları (Ara adımlar)
Ajanın düşünme, komut yürütme, dosya okuma/yazma ve çıktı üretme adımlarını canlı bildirir.
- **Kullanıcı Girişi Adımı:**
  `{"event":"step_update","step_update":{"conversation_id":"...","step_index":0,"state":"DONE","step_type":"user_input"}}`
- **Metin/Düşünce Akışı:**
  `{"event":"step_update","step_update":{"step_index":1,"state":"ACTIVE","step_type":"agent_response","text_delta":"..."}}`
  Tamamlandığında `state="DONE"`, `duration_seconds` ve `usage` içerir.
- **Araç Çağrısı Başlangıcı:**
  `{"event":"step_update","step_update":{"step_index":2,"state":"ACTIVE","step_type":"tool","tool_name":"run_command","tool_info":{"name":"run_command","parameters":{"CommandLine":"..."}}}}`
- **Araç Çağrısı Bitişi:**
  `{"event":"step_update","step_update":{"step_index":2,"state":"DONE","step_type":"tool","tool_name":"run_command","duration_seconds":6.25,"tool_info":{"name":"...","output":"..."}}}`

### 1.3 `result` Olayı (Her zaman son satır)
Tur sona erdiğinde üretilir.
```json
{
  "event": "result",
  "result": {
    "conversation_id": "864b8f93-16e0-4693-8e49-2487dfba0559",
    "status": "SUCCESS",
    "response": "...",
    "duration_seconds": 4.26,
    "num_turns": 1,
    "structured_output": { ... },
    "usage": {
      "input_tokens": 6830,
      "output_tokens": 126,
      "thinking_tokens": 123,
      "cache_read_tokens": 0,
      "total_tokens": 6956
    }
  }
}
```

---

## 2. G2 Kesinleşen Çözüm: Stdin Üzerinden İstem Besleme

Windows'un 32 767 karakter komut satırı sınırını ve tırnak kaçış kırılganlığını aşmak için `--input-format stream-json` incelenmiştir.

### Test Edilen ve Doğrulanan Format:
`agy --input-format stream-json --output-format stream-json` çağrıldığında stdin'e şu NDJSON satırı verilir:
```json
{"event": "user", "message": {"content": "<TAM_ISTEM_METNI>"}}
```
- Desteklenmeyen veya eksik event verildiğinde `agy` şu hatayı üretir:
  - `stream input message is missing the "event" field`
  - `ignoring unsupported stream input message event "..."`
  - `stream input "user" message is missing the "message" field`
  - `stream input "user" message has no content`
- Doğru biçim olan `{"event": "user", "message": {"content": "..."}}` verildiğinde `agy` hatasız şekilde turu başlatır ve normal `stream-json` çıktısı üretir (Returncode: 0).
- **AGENT BUS Kararı:** Runner tüm tur istemlerini stdin üzerinden bu formatla gönderecektir.

---

## 3. Yapılandırılmış Çıktı (`--json-schema`) Davranışı

- `--json-schema '<JSON_SCHEMA_STR>'` parametresi verildiğinde:
  1. `init` nesnesinde `"json_schema"` alanı görünür.
  2. Model görev tamamlandığında şemaya uygun bir JSON bloğu üretir ve son adımda `finish` aracını çağırır.
  3. En son `result` nesnesinde `"structured_output"` alanı doğrudan ayrıştırılmış Python/JSON objesi olarak yer alır.
- **AGENT BUS Kararı:** Ajan sözleşmesi (§6) JSON şeması doğrudan `--json-schema` ile zorlanacaktır.

---

## 4. Zaman Aşımı (`--print-timeout`) Davranışı

- `--print-timeout <duration>` (örn. `2s`, `10m`) aşıldığında:
  - Konsola `[agy] print timeout after 2s with turn in progress; returning partial output` uyarısı basılır.
  - CLI `returncode: 0` ile çıkar!
  - Son `result` nesnesinde `status: "SUCCESS"` kalır ancak `response` boş kalır ve `structured_output` üretilmez.
- **AGENT BUS Kararı (G4 Doğrulaması):** `result.status == "SUCCESS"` olması işin bittiği anlamına gelmez. Durum yalnız ve yalnız `structured_output` veya yanıt içerisindeki sözleşme JSON'undan (`status: "done"`) çıkarılır. JSON yoksa iş `interrupted` / `needs_review` sayılır.

---

## 5. Hata ve 429 Kota Davranışı

- Hatalı durumlarda `result` nesnesi:
  `{"event":"result","result":{"status":"ERROR","error":"...","response":""}}`
  şeklinde döner ve çıkış kodu 1 olur.
- 429 kota durumunda stderr veya stream çıktısında `429` / `quota` ibareleri yakalanarak artan bekleme (30s, 2m, 8m) uygulanır.
