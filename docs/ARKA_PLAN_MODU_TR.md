# MathMagic MCP Pro v0.2 — Arka planda çalışma güvenliği (deneysel)

## Neler doğrulandı?

Kullanılan InDesign MCP: https://github.com/nutriandrea/adobe-indesign-mcp
Bu araç Windows üzerinde COM ya da UXP köprüsüyle InDesign'ı kontrol edebilir.

MathMagic Pro 9.31 için **pencereyi öne getirmeden LaTeX dönüştürme ve kaydetme** sağlayan, belgelenmiş ve doğrulanmış bir API tespit edilemedi. InDesign'ın arka planda çalışması MathMagic editörünün de arka planda yazabildiğini kanıtlamaz.

Bu sürüm MathMagic'e klavye veya fare komutları **göndermez**. v0.1 sürümünün odak kullanan `mathmagic_create_equation`, `mathmagic_edit_equation`, `mathmagic_run_batch_first` ve `mathmagic_cleanup_marker` araçları v0.2 güvenli sunucusunda **görünmez ve çağrılamaz**. v0.1 dosyaları diskte saklanır; eski sunucu ayrıca başlatılırsa bu sınırlama geçerli değildir.

## Kurulum

1. Depoyu klonlayın (`git clone https://github.com/mrtersn9-cpu/mathmagic-mcp-pro.git`). Proje eskiden `e-icerik_editor/tools/mathmagic-mcp-pro/` klasöründeydi.
2. Windows PowerShell'de bu dizine geçin.
3. `powershell -ExecutionPolicy Bypass -File .\install_background.ps1` komutunu çalıştırın.
4. Claude Desktop'ı tamamen kapatıp yeniden açın.
5. Sırayla `mathmagic_background_policy` ve `mathmagic_background_probe` çağırın.

Kurulum betiği mevcut Claude Desktop ayarını yedekler ve yalnızca `mathmagic-mcp-pro` girdisini yeni sunucuya yönlendirir. `indesign` girdisi korunur.

## Araçlar

- `mathmagic_background_policy`: Güvenli modun kurallarını ve mevcut kısıtını bildirir.
- `mathmagic_background_probe`: Windows UI Automation özelliklerini salt okunur inceler; pencereyi aktif yapmaz, fare/klavye kullanmaz.
- `mathmagic_background_plan`: LaTeX'i doğrular; bu sürümde arka planda yazma işleminin engelli olduğunu açıkça bildirir.
- `mathmagic_prepare_offline_batch`: 100 adede kadar denklemin girdilerini .tex dosyalarına dönüştürmeden hazırlar. Sadece `confirm=true` ile bu dosyaları yazar. **MathMagic formülü üretmez.**

## Windows test sırası

1. InDesign 2026 ve MathMagic Pro 9.31'i açın; yalnızca orijinal olmayan test belgesi kullanın.
2. `mathmagic_background_policy` çalıştırın.
3. MathMagic editörü açıkken `mathmagic_background_probe` çalıştırın.
4. Chrome veya Excel'i aktif pencere yapıp `mathmagic_background_probe` tekrar çalıştırın.
5. `foreground_unchanged_at_samples` yalnızca iki örnekleme anındaki aynı pencereyi gösterir; hiçbir ara anda odağın değişmediğinin kanıtı **değildir**.
6. UIA kontrolü mevcut olsa bile bu, MathMagic editörünün formül alma, dönüştürme ve kaydetmeyi odağı değiştirmeden yapabildiğinin kanıtı değildir.

## Ortak çalışma ve sınırlamalar

MathMagic MCP, `nutriandrea/adobe-indesign-mcp` sunucusunu değiştirmez. İki sunucu arasında paylaşımlı belge kilidi henüz yok; aynı belgeyi eşzamanlı düzenlemeyin. MathMagic tarafından düzenlenebilir gerçek formüllerin arka planda oluşturulması Windows üzerinde henüz doğrulanmadı.

**Durum:** Arka plan uyumluluk tanılaması ve çevrimdışı girdi hazırlama çalışır. Tam otomatik arka plan formül dizgisi henüz desteklenmez.
