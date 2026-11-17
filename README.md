# MathMagic MCP Pro (Windows / InDesign 2026) · v0.4.1

[![Status](https://img.shields.io/badge/status-beta%20(canl%C4%B1%20test%20edildi)-yellow)](#neler-doğrulandı-neler-doğrulanmadı)

Bu MCP sunucusu, **Claude** (Claude Code / Claude Desktop) ile **Adobe InDesign 2026** ve **MathMagic Pro 9.31 InD** arasında çalışır. InDesign metin çerçevelerine **yerel, düzenlenebilir, gömülü MathMagic formülleri** yerleştirir. Bu iş arka planda yürür; siz başka programlarda çalışmaya devam edebilirsiniz. Mevcut InDesign MCP'nizi değiştirmez, onun yanında ayrı bir araç seti olarak çalışır.

> **Depo:** https://github.com/mrtersn9-cpu/mathmagic-mcp-pro
> Proje önceden `e-icerik_editor` deposunun `tools/mathmagic-mcp-pro` klasöründeydi. 17.11.2026'da commit geçmişi korunarak bu bağımsız depoya taşındı.

## Temel ilkeler

- **Yalnız pencere mesajları ve InDesign COM kullanılır.**
  - MathMagic `WM_CHAR`, `WM_COMMAND`, `WM_SETTEXT` ve `BM_CLICK` mesajlarıyla yönetilir.
  - InDesign, sabit JSX içeren `DoScript` çağrılarıyla yönetilir.
  - Klavye/fare simülasyonu, pano, `SetFocus`/`SetForegroundWindow` ve ekran görüntüsü/OCR **kullanılmaz**.
- **Tek kanal.** MathMagic yalnız bu sunucunun `mathmagic_*` araçlarıyla sürülür. Windows MCP, computer-use veya tuş/fare gönderen betikler MathMagic ya da InDesign penceresinde kullanılmaz. Bu kural, sunucunun istemciye verdiği talimatlarda da yer alır.
- **Lisans/Try penceresine dokunulmaz.** Araç `LICENSE_REQUIRED` döndürür; pencereyi kullanıcı kapatır.
- **Onay gerekir.** Değişiklik yapan her araç `confirm=true` ister. Süreçler arası kilit vardır: başka bir oturum çalışıyorsa araç `BUSY` döndürür.
- **Kaydetme yalnız istenirse yapılır** (`save_every` veya `mathmagic_save_document`). Formül eklemeden önce `mathmagic_backup_indd` ile yedek alınır.

## Mimari

```text
Claude
  ├── InDesign MCP ─────────── metin çerçeveleri, stiller, sayfalama, tekil [[MM:ID]] işaretçileri
  └── mathmagic-mcp-pro (stdio, yerel Python)
        ├── çevrimdışı mod (varsayılan, odak almaz)
        │     MathMagic: temizle + LaTeX yaz + TeX dönüştür (tek mesaj kuyruğu) → Save As EPS (+ LaTeX geri doğrulama)
        │     InDesign: işaretçiye satır içi yerleştir, göm, %100 ölçek, Default Baseline, etiketle, tek "Geri Al" adımı
        └── eklenti modu: InDesign MathMagic eklentisi New/Edit Equation + Update (pencereleri öne getirir)
```

## Araçlar (27)

**Salt okunur:**
- `mathmagic_policy`, `mathmagic_preflight`, `mathmagic_status`, `mathmagic_capabilities` (213 menü komutu ve 13 eklenti eyleminin canlı envanteri)
- `mathmagic_inspect_indesign`, `mathmagic_probe_uia`, `mathmagic_preview_equation`, `mathmagic_preview_batch`
- `mathmagic_verify_equation`, `mathmagic_list_equations`, `mathmagic_get_style`, `mathmagic_capture_editor`

**Değişiklik yapanlar** (`confirm=true` gerekir):
- `mathmagic_launch`, `mathmagic_dismiss_dialogs`
- `mathmagic_create_equation`, `mathmagic_edit_equation`
- `mathmagic_export_equation` (EPS, SVG, MathML, PNG, LaTeX…), `mathmagic_render_eps`, `mathmagic_place_eps`
- `mathmagic_run_batch`, `mathmagic_rerender_equations`
- `mathmagic_set_style`, `mathmagic_apply_styleset`
- `mathmagic_prepare_offline_batch`, `mathmagic_backup_indd`, `mathmagic_save_document`, `mathmagic_cleanup_marker`

Ayrıntılar: [`docs/PRO_V04_TR.md`](docs/PRO_V04_TR.md) · Komut envanteri: [`docs/MATHMAGIC_KOMUT_ENVANTERI_TR.md`](docs/MATHMAGIC_KOMUT_ENVANTERI_TR.md)

## Soru bankası iş akışı

1. `mathmagic_preflight` çalıştırılır. Ardından kitap yazı tipi ve puntosu bir kez `mathmagic_set_style` ile verilir. Örnek: `name="SB Matematik 10.4"`, `font="Times New Roman"`, `size_pt=10.4`, `variable_italic=true`.
2. InDesign MCP metni yazar. Her formülün yerinde tekil bir işaretçi bulunur (`[[MM:Q0001-M1]]`). Ardından belge kaydedilir.
3. Sırasıyla `mathmagic_backup_indd` ve `mathmagic_preview_batch` çalıştırılır.
4. Toplu iş çalıştırılır:
   ```
   mathmagic_run_batch(manifest_path, document, mode="offline", verify_latex=true,
                       remove_markers=true, time_budget_s=600, save_every=50, confirm=true)
   ```
   `next_index` doluysa aynı çağrı `start_index=next_index` ile tekrarlanır.
5. `mathmagic_list_equations` ile kontrol edilir. Belgede `[[MM:` kalmamalı; `placeholders` ve `not_embedded` 0 olmalı.

Manifest biçimi: `{"equations":[{"id":"Q0001-M1","marker":"[[MM:Q0001-M1]]","latex":"\\frac{3}{4}","size_pt":11.5}]}`

**soru-bankasi-uret-pro skill'i** soru bankası JSON'undan işaretçili InDesign iş emirlerini ve ünite bazlı manifestleri otomatik üretir (`scripts/prepare_mathmagic.py`). Protokolü `indesign/MATHMAGIC-ENTEGRASYON.md` belgesindedir.

**Dizgi notu:** Üst üste kesir içeren satır içi formül paragraflarına sabit satır aralığı verin (metin puntosunun yaklaşık 1,75 katı). Otomatik satır aralığı MathMagic'in taban çizgisi kaydırmasını hesaba katmaz ve kesirler üst üste biner (canlı test).

## Sonuç durumları

| Durum | Anlamı |
|---|---|
| `INSERTED_VERIFIED` | Formül yerleşti, gömüldü, EPS'te MathMagic formül verisi (MMF) var, LaTeX doğrulaması geçti |
| `SKIPPED_ALREADY_DONE` | Aynı LaTeX daha önce eklenmiş (etiketteki SHA eşleşti) |
| `LATEX_MISMATCH` | MathMagic farklı bir yapı kurdu. `latex_exported` alanı MathMagic'in ne ürettiğini gösterir; kaynak düzeltilir. |
| `EMPTY_RENDER` | Formül iki denemede de boş çıktı (yazılan karakterler kayboldu); yeniden çalıştırılır |
| `LICENSE_REQUIRED` / `MATHMAGIC_NOT_READY` | Lisans/Try penceresi açık; kullanıcı kapatır |
| `MARKER_COUNT` | İşaretçi yok ya da birden fazla |
| `BUSY` | Başka bir oturum MathMagic kilidini tutuyor |

## Kurulum (Claude Code)

Gerekenler: Windows 10/11, Python 3.10+, `pywin32`, Adobe InDesign 2026, MathMagic Pro 9.31 InD ve InDesign `Plug-Ins\MathMagic CC2026-64bit` eklentisi.

```powershell
git clone https://github.com/mrtersn9-cpu/mathmagic-mcp-pro.git C:\Users\<kullanıcı>\mcp-servers\mathmagic-mcp-pro
cd C:\Users\<kullanıcı>\mcp-servers\mathmagic-mcp-pro
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-windows.txt
.\.venv\Scripts\pip install pytest
.\.venv\Scripts\python -m pytest -q tests     # 82 test
```

`mathmagic-mcp-pro.json` dosyası (yolları kendi klasörünüze göre düzeltin):

```json
{"type":"stdio","command":"C:\\...\\mathmagic-mcp-pro\\.venv\\Scripts\\python.exe",
 "args":["-u","C:\\...\\mathmagic-mcp-pro\\server_pro.py"],
 "env":{"MATHMAGIC_EXE":"C:\\Program Files (x86)\\MathMagic Pro Edition\\MathMagic Pro 9.31 InD.exe",
        "MATHMAGIC_DEFAULT_MODE":"offline"}}
```

```bash
# Git Bash (Windows PowerShell 5.1, yerel programlara verilen JSON'daki tırnakları siler)
claude mcp add-json mathmagic-mcp-pro "$(cat mathmagic-mcp-pro.json)" -s user
```

`install.ps1` eski v0.1 sunucusunu (`server.py`) Claude Desktop'a kaydeder. Pro sürüm için yukarıdaki kaydı kullanın. Kayıttan sonra yeni bir Claude oturumu açın. Mevcut InDesign MCP kaydına dokunulmaz.

## Ölçülen hız (deneme modu)

| Mod | Süre |
|---|---|
| Çevrimdışı, LaTeX doğrulaması kapalı | 1,8–2,3 sn/formül |
| Çevrimdışı, LaTeX doğrulaması açık | 2,8–4,5 sn/formül (uzun oturumda yükselir; çalışma belgesi 25 kullanımda bir tazelenir) |
| Eklenti modu | 2,5–2,8 sn/formül; pencereleri öne getirir |

Lisanslı sürümde toplu dönüştürme (File > Convert) daha hızlı bir yol olabilir; deneme sürümü bunu engelliyor, henüz test edilmedi.

## Neler doğrulandı, neler doğrulanmadı

- ✅ **Canlı uçtan uca test** (17.11.2026, test belgesi). Soru bankası örneğindeki 16 formül çevrimdışı modda yerleşti; sonuçlar `INSERTED_VERIFIED` ve LaTeX doğrulaması `EQUIVALENT`/`EXACT`. Hiçbir işlem kullanıcının uygulamasından odak almadı. Formüllerin tamamı gömülü ve tek StyleSet'te.
- ✅ **Yazı tipi seçimi:** StyleSet'te Times New Roman uyarısız çalıştı. Myriad Pro ve Helvetica Neue, MathMagic'te yazı tipi uyarısı veriyor.
- ✅ **Kullanıcı girdisi koruması:** Kullanıcı Alt+Tab ile Alt tuşunu basılı tutarken MathMagic'e giden karakterler kayboluyordu. Araç artık tuşun bırakılmasını bekliyor ve boş formülü bir kez yeniden deniyor (canlı doğrulandı).
- ✅ **Birim testleri:** 82 test geçiyor.
- ⚠️ **Doğrulanmayanlar:**
  - Tablo hücresindeki işaretçi canlı denenmedi. InDesign MCP'nin tablo araçları bu ortamda hata verdi.
  - PDF dışa aktarma Helvetica Neue stilinde MathMagic hatası veriyor.
  - Lisanslı sürüm davranışı: "Demo" filigranı, açılış penceresi ve toplu dönüştürme.
- ❌ **Bilinen sınırlar:**
  - Eklenti modu pencereleri öne getirir.
  - Deneme sürümü her yeni süreçte lisans penceresi açar.
  - Formüllerin matematiksel doğruluğunu ve son baskı kalitesini insan editör onaylar.

## Belgeler

- [v0.4 kullanım kılavuzu](docs/PRO_V04_TR.md) · [MathMagic komut envanteri](docs/MATHMAGIC_KOMUT_ENVANTERI_TR.md)
- [Arka plan modu](docs/ARKA_PLAN_MODU_TR.md) · [Mimari](docs/MIMARI.md) · [API](docs/API.md)
- [Kalite kontrol](docs/KALITE_KONTROL.md) · [Sorun giderme](docs/SORUN_GIDERME.md) · [Güvenlik yol haritası](docs/GUVENLIK_YOL_HARITASI.md)
- Eski sürümler: [v0.3](docs/PRO_V03_TR.md) · [Kurulum (v0.1)](docs/KURULUM_TR.md)

## Lisans

Kaynak kodu `LICENSE` altındaki MIT lisansıyla sağlanır. MathMagic ve Adobe InDesign ticari ürünlerdir ve bu depoya dahil değildir.
