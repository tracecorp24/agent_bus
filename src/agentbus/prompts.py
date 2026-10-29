"""Agent Bus sistem talimatları, istem şablonları ve JSON şemaları."""

import json

# §6 Ajan Sözleşmesi JSON Şeması
RESULT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["done", "needs_input", "blocked", "failed"],
            "description": "Görevin son durumu"
        },
        "summary": {
            "type": "string",
            "description": "Yapılan işin kısa ve net özeti"
        },
        "files_changed": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Değiştirilen veya eklenen dosyaların göreceli yolları"
        },
        "tests": {
            "type": "string",
            "description": "Çalıştırılan testlerin sonucu veya test komutları"
        },
        "question": {
            "type": ["string", "null"],
            "description": "Eğer status needs_input ise orkestratöre/insana yöneltilen soru, aksi halde null"
        }
    },
    "required": ["status", "summary", "files_changed", "tests", "question"]
}

RESULT_JSON_SCHEMA_STR = json.dumps(RESULT_JSON_SCHEMA)

# §6 Sistem Talimatı (Her işin ilk istemine eklenir)
SYSTEM_CONTRACT_PROMPT = """
SEN AGENT BUS TARAFINDAN YÖNETİLEN BİR AJANSIN.
AŞAĞIDAKİ SÖZLEŞMEYE KESİNLİKLE UYMAK ZORUNDASIN:

1. YETKİ VE DOSYA SINIRLARI:
- Çalışma dizinin sana tahsis edilen özel dizindir.
- Yalnızca izin verilen dosya yollarına yazabilirsin. İzin dışındaki dosyalara dokunma.
- Soru sorma araçlarını (ask_question vb.) KULLANMA. İnsanla doğrudan etkileşim yerine ihtiyacın olan bilgiyi sonuç JSON'unda belirt.

2. İLETİŞİM:
- Diğer ajanlarla veya üst yapay zekâ (orkestratör) ile konuşmak için ortamda tanımlı agentbus komutlarını kullanabilirsin.
- Eğer bilgiye ihtiyacın varsa status'u "needs_input" olarak işaretle ve sorunu "question" alanına yaz.

3. SONUÇ RAPORU:
- Görevin bittiğinde veya tıkandığında son yanıtını MUTLAKA JSON formatında bitir.
- Şema:
  {
    "status": "done" | "needs_input" | "blocked" | "failed",
    "summary": "özet",
    "files_changed": ["dosya1", "dosya2"],
    "tests": "test sonucu",
    "question": null veya "soru metni"
  }
"""

# §5.10 Resume İstemi Şablonu (Kesinti sonrası devam turu)
RESUME_PROMPT_TEMPLATE = """
DİKKAT: Önceki adımın beklenmedik bir kesintiye (süreç kapanması veya zaman aşımı) uğradı.
Sohbet geçmişin ve çalışma alanın korunmuştur.

Şunları yap:
1. `git status` ve çalışma alanındaki son değişiklikleri kontrol et.
2. Tamamlanmamış işleri tamamla, zaten tamamlanmış olanları tekrarlama.
3. İşi bitirdiğinde sözleşmeye uygun sonuç JSON'u ile rapor ver.
"""
