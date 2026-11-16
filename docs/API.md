# MCP araç sözleşmeleri

Kökte `server.py`; `stdio` UTF-8 satır başına bir JSON-RPC mesajı. Standart MCP `tools/list` üzerinden şema ve açıklamalar alınabilir. Araca göre JSON argümanları:

## 1. `mathmagic_preflight`

`{}`. Bağımlılık, `InDesign 2026`, MathMagic `InD.exe`, eklenti klasörü durumu; hiçbir değişiklik yapmaz.

## 2. `mathmagic_inspect_indesign`

`{}`. COM ile açık belge, seçim ve `New Equation` / `Edit Equation` eylemlerini sorgular. `menuActions` adlarını bulamıyorsa işlemden önce yerel eklentiyi kontrol edin.

## 3. `mathmagic_preview_equation`

`{"latex":"\\frac{1}{2}","mode":"create","marker":"[[MM:Q001]]"}`. `mode` varsayılan `create`; `marker` boşsa mevcut InDesign seçimi kullanılır. Yalnız önizleme.

## 4. `mathmagic_create_equation`

`{"latex":"\\frac{1}{2}","marker":"[[MM:Q001]]","confirm":true,"window_timeout":25}`.

`confirm` verilmezse veya `false` ise **yalnız önizleme**. Başarılı klavye gönderimi `SUBMITTED_UNVERIFIED` olarak raporlanır.

## 5. `mathmagic_edit_equation`

`{"latex":"x^3","confirm":true}`. InDesign'da mevcut **MathMagic nesnesinin seçili** olması gerekir. Editör penceresinde `Ctrl+A` ve yeniden yapıştırma kullanır. İfade eşdeğerliğini ve nesne korumasını otomatik doğrulamaz.

## 6. `mathmagic_backup_indd`

`{"folder":"D:\\YYB\\Yedekler","confirm":true}`. Dosya sistemindeki son kaydedilmiş `.indd` dosyasını farklı klasöre kopyalar. Kaydedilmemiş değişiklikler yedeğe dahil değildir.

## 7. `mathmagic_check_marker`

`{"marker":"[[MM:Q001]]"}`. İşaretin bulunup bulunmadığı ve metin akışı konumuyla ilgili sınırlı bilgi. Matematiksel nesne bütünlüğü kanıtı değil.

## 8. `mathmagic_preview_batch`

`{"manifest_path":"C:\\Tools\\mathmagic-mcp-pro\\examples\\equations.json"}`. Manifest JSON'da `equations`: `[{"id":"Q001", "marker":"[[MM:Q001]]", "latex":"..."}]`. En fazla 100 öğe; işaretler tekil olmalı.

## 9. `mathmagic_run_batch_first`

`{"manifest_path":"C:\\...\\equations.json","start_index":0,"confirm":true,"stop_on_unverified":true}`.

İsmi tarihsel; `start_index` verilirse seçilen dizin öğesini işler. Her çağrıda **tek formül** ve sonrasında `PAUSED_FOR_REVIEW`. Aynı manifest ve bir sonraki `start_index` ile devam edin.

## 10. `mathmagic_cleanup_marker`

`{"marker":"[[MM:Q001]]","confirm":true,"human_verified":true}`. Gözle kontrol edilmiş nesnenin yanındaki tekil yer tutucuyu siler. Çift onay olmadan hiçbir şey silmez.

## Dönüş değerleri

- `ok`: aracın kendi işlem adımlarındaki sonuç; **matematiksel kalite sertifikası değildir**.
- `dry_run`: mutasyon yapmayan çağrı.
- `status`: `SUBMITTED_UNVERIFIED` / `FAILED_OR_PARTIAL` / `PAUSED_FOR_REVIEW`.
- `requires_manual_review`: kalite kontrol gerekli.
- `job_id`, `audit_log`: takip/inceleme.

## Konfigürasyon değişkenleri

- `MATHMAGIC_EXE`: tam `MathMagic Pro 9.31 InD.exe` yolu.
- `INDESIGN_PROGID`: `InDesign.Application` veya sürüm-spesifik ProgID.
- `MATHMAGIC_NEW_ACTION`: tespit edilmiş tam menü eylem adı.
- `MATHMAGIC_EDIT_ACTION`: tespit edilmiş tam menü eylem adı.
- `MATHMAGIC_CONVERT_KEYS`: varsayılan `+{ENTER}` (Shift+Enter).
- `MATHMAGIC_SAVE_KEYS`: varsayılan `^s` (Ctrl+S).
- `MATHMAGIC_CLOSE_EDITOR`: varsayılan `false`; elle doğrulamadan `true` yapmayın.
- `MATHMAGIC_LOG_DIR`: log klasörü.

## Hata biçimi

Aracın kendisi `ok:false` döndürürse MCP `isError:true` ayarlanır. Giriş şeması eksikse JSON-RPC `-32602` hatası gelir. Düz stdout logları protokolü bozacağı için diagnostik yalnız stderr'e yazılır.