# Soru bankası ve föy dizgisi için kalite kontrol

Aşağıdaki plan **baskı öncesi doğrulama önerisidir**; mevcut MCP'nin bunları otomatik geçtiği anlamına gelmez.

## Bir formülde kontrol edilecekler

1. Matematiksel içerik: kesir pay/payda, kök kapsamı, üs/alt indis, integral sınırı, denklem işareti, eksi/tire.
2. InDesign bağlamı: metne bağlı nesne olup olmadığı; metin akışında boşluk, satır kırılması, temel çizgi (baseline).
3. MathMagic yerelliği: nesneyi çift tıklayınca doğru MathMagic editörü açılıyor mu? Denklemi değiştirmek mümkün mü?
4. Tipografik kurallar: soru metni **9 punto**; mavi kutu başlığı **9**, içeriği **8**, `Aklında Tut` metni **8** punto; çizimli şekillerde **0,75 pt** çizgi ve **8 punto** etiket. Bunlar otomatik uygulanmaz; mevcut InDesign dizgi stilinin denetiminde kontrol edilmelidir.
5. Nesne kenar boşlukları: yerleşimi bozacak taşma yok; şablon ve sayfa yapısı korunmuş.
6. Kaynak PDF'deki şekiller ayrı değerlendirilmeli; MathMagic MCP **görsel/şekil kopyalama** aracı değildir.

## Pilot kabul kriterleri

- Kesir, kök, üs, alt indis, denklem, integral için en az birer gerçek işlem.
- Kaynak ve çıktı matematiksel olarak aynı.
- Düzenlenebilirlik: tüm örneklerde MathMagic ile yeniden açma ve kaydetme.
- Matbaa PDF'si ile karşılaştırma: atlayan glif, kaymış baseline, font problemi yok.
- Tek test hatası görüldüğünde toplu işlem devam ettirilmemeli.
- Başarılı QA sonucu kullanıcı tarafından açıkça işlenmeli; MCP kendiliğinden başarı ilan etmez.

## Baskı öncesi kayıt

Her denkleme `Q001` gibi tanımlayıcı verin. Örnek rapor alanları: `job_id`, `id`, `sayfa`, `soru`, `kaynak_latex`, `ekleme_konumu`, `mathmagic_açıldı`, `kaydedildi`, `double_click_edit`, `yerleşim_kontrol`, `sonuç`. Kaynak LaTeX'i denetim raporunda tutmak istiyorsanız ayrıca kurum içi gizli dosyada saklayın; MCP logu yalnız hash saklar.