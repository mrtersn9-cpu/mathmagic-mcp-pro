# Windows / Claude Desktop / InDesign 2026 kurulum rehberi

## 1. Sistem ön koşulları

- Windows 10/11, oturumu açık masaüstü (kilit ekranında GUI otomasyonu çalışmaz).
- Adobe InDesign **2026** açık ve en az bir test belgesi mevcut.
- MathMagic Pro **9.31** kurulmuş. Gözlemlenen yol: `C:\Program Files (x86)\MathMagic Pro Edition\MathMagic Pro 9.31 InD.exe`.
- MathMagic **CC2026-64bit** klasörü `C:\Program Files\Adobe\Adobe InDesign 2026\Plug-Ins\` içine kopyalanmış.
- InDesign üst menüsünde `Plug-Ins → MathMagic → New Equation` ve `Edit Equation` çalışıyor.
- Python 3.10+ ve Python başlatıcısı `py -3` çalışıyor. `python --version` ile de kontrol edin.

**Lisans:** MathMagic ücretli ürünse kurulum ve kullanımı için geçerli lisans gerekir. Lisans pencereleri otomasyonu bloke edebilir.

## 2. Kur

PowerShell:

```powershell
cd C:\Tools\mathmagic-mcp-pro
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

`install.ps1` şunları yapar:

1. Proje içinde `.venv` oluşturur.
2. `pywin32`, `pywinauto` kurar.
3. `%APPDATA%\Claude\claude_desktop_config.json` varsa timestamp ekleyerek yedekler.
4. **Mevcut** `mcpServers` girdilerini silmeden yeni `mathmagic-mcp-pro` girdisini ekler.

Betik sorun çıkartırsa elle yapılandırma örneği `examples/claude_desktop_config.snippet.json` dosyasındadır. **Mevcut JSON'u tamamen değiştirip eski InDesign MCP'yi silmeyin.** Yalnız `mcpServers` içine tek yeni anahtar ekleyin.

## 3. Yeniden başlat ve doğrula

Claude Desktop'ı tamamen kapatın (arka plan simgesinden de çıkın), tekrar açın. Claude'a:

```text
MathMagic MCP'nin mathmagic_preflight ve mathmagic_inspect_indesign
araçlarını çalıştır. MathMagic New Equation ve Edit Equation
menü eylemlerini gerçek InDesign'dan bul. Belgeyi değiştirme.
```

Eylem adları program diline göre değişiyorsa `MATHMAGIC_NEW_ACTION` ve `MATHMAGIC_EDIT_ACTION` değerlerini gerçek sonuçtaki adlarla değiştirin. Adların tam eşleşmesi gerekir.

## 4. İlk denklem testi

1. **Yeni, boş bir test INDD** oluşturun. Orijinal şablona dokunmayın.
2. Metin çerçevesi ve içine yazı ekleyin; metin imlecini formülün geleceği yere koyun.
3. `mathmagic_preview_equation(latex="\\frac{2}{3}")` çalıştırın.
4. `mathmagic_create_equation(latex="\\frac{2}{3}", confirm=true)` çalıştırın.
5. MathMagic penceresinin açıldığını, LaTeX'in **dönüştürüldüğünü**, InDesign'da doğru yerde göründüğünü kontrol edin.
6. Nesneye çift tıklayın; gerçek MathMagic editörü yeniden açılabiliyorsa birinci pilot testi kaydedin.

`SUBMITTED_UNVERIFIED` sonucu **başarı onayı değildir**. Fare odağı, lisans ekranı veya dönüşüm kısayolu sorunları yaşanabilir.

## 5. Mevcut InDesign MCP ile kullanım

Mevcut InDesign MCP ile istediğiniz metin çerçevesini seçin veya örneğin `[[MM:Q001]]` işaretçisini oluşturun. Ardından MathMagic MCP:

```text
mathmagic_preview_equation(latex="\\sqrt{25}", marker="[[MM:Q001]]")
mathmagic_create_equation(latex="\\sqrt{25}", marker="[[MM:Q001]]", confirm=true)
```

MathMagic nesnesinin oluştuğunu **manuel** doğrulayın. Ardından `mathmagic_cleanup_marker(marker="[[MM:Q001]]",confirm=true,human_verified=true)` ile kalan yer tutucuyu silebilirsiniz.

**Çok önemli:** InDesign MCP, MathMagic işlemi devam ederken **başka bir seçim veya düzenleme yapmamalı**. Aksi halde yanlış yere formül konulabilir.

## 6. Toplu iş akışı

1. InDesign MCP ile istenen yerlere `[[MM:Q001]]`, `[[MM:Q002]]` ... işaretleri yerleştirin.
2. `examples/equations.json` biçiminde manifest dosyası hazırlayın.
3. `mathmagic_preview_batch` ile kontrol edin.
4. Kaydedilmiş `.indd` dosyasını `mathmagic_backup_indd` ile farklı klasöre kopyalayın. **Kaydedilmemiş değişikliklerin yedekte olmayacağını** unutmayın.
5. `mathmagic_run_batch_first(manifest_path="...",start_index=0,confirm=true)` çalıştırın.
6. İlk formülü kontrol edin; doğruysa işaretçiyi kaldırın.
7. `start_index=1`, sonra `2` ile devam edin.

MCP hiçbir noktada 100 formülün otomatik kusursuz dönüştüğünü iddia etmez. Kasıtlı kontrol kapıları vardır.

## 7. Günlükler

Varsayılan log klasörü: `%USERPROFILE%\MathMagicMCP\logs\mm-YYYYMMDD.jsonl`.

Günlükler işlem kimliğini, kullanılan komutu, LaTeX SHA256 özetini, zaman damgasını ve hata varsa açıklamayı tutar. Ham formül metnini saklamaz.

## 8. Kaldırma

Claude yapılandırmasında yalnız `mathmagic-mcp-pro` anahtarını silin. Mevcut InDesign MCP girişlerini koruyun. Proje klasörünü silebilirsiniz; InDesign'ın resmî MathMagic eklentisini silmeniz gerekmez.