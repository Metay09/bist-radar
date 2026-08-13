# BIST Radar Dashboard

Dashboard is a React 18 + TypeScript + Vite PWA served by the isolated `bist-radar-web` container.
It is available only at `http://127.0.0.1:8770`; use an existing private SSH or Tailscale tunnel if
remote access is needed. No public bind or Cloudflare tunnel is created.

Pages are Radar, Signals, Paper Portfolio, Analysis/Shadow Intelligence, System, and symbol detail.
Financial calculations remain in FastAPI. The browser receives bounded chart windows and aggregate
read-only endpoints. Missing data is displayed as missing, never zero. Offline mode warns explicitly
and the service worker never caches API financial responses.

Desktop uses a compact side navigation and mobile uses safe-area-aware bottom navigation. The UI
contains keyboard focus states, semantic status colors, loading/error/empty states and Turkish locale
formatting. Install via the browser's PWA action when served from localhost.

## İşlem planı

Güçlü adaylar ve hisse detayı tek bir “hemen al” fiyatı vermez. Backend mevcut ATR, son yapısal dip,
breakout mesafesi ve risk motoruyla referans fiyat, giriş bölgesi, breakout seviyesi, stop, üç hedef ve
risk/getiri üretir. `GIRIS_BEKLENIYOR`, `GIRIS_BOLGESINDE`, `BREAKOUT_ONAYI`, `KACMIS_KOVALAMA` ve
`GECERSIZ` durumları planın nasıl okunacağını açıklar. Pozisyon boyutu varsayılan paper sermayesi ve
işlem başına maksimum risk üzerinden advisory olarak gösterilir; emir açmaz.

Eski veri planı gizlice güncelmiş gibi sunulmaz. Piyasa kapalı veya veri eskiyse plan son tamamlanmış
araştırma barına ait olduğunu belirtir. Stop kırmızı, hedefler yeşil ve nötr seviyeler mavi/gri gösterilir.

## Mobil kullanım ve rehber

Telefon görünümünde sidebar kapanır; Radar, Sinyaller, Portföy, Analiz ve Sistem için safe-area uyumlu
ikonlu bottom navigation açılır. Uzun sinyal tabloları yatay taşma yerine özet kartlara dönüşür. İlk
açılışta Türkçe on adımlı ürün turu gösterilir; tur atlanabilir, tercih yalnız tarayıcı local storage'da
saklanır ve “Yardım / Rehber” düğmesinden yeniden başlatılabilir.

Gerçek Chromium kabulü 360×800, 390×844, 412×915 ve 768×1024 CSS piksel viewport'larında yapılır.
Bu boyutlarda masaüstü tablosu ile kenar çubuğu görünmez; alt navigasyon görünür ve sayfa yatay taşmaz.

Backend enumları değiştirilmeden kullanıcı metinleri Türkçeleştirilir. Radar güncel adayları gösterir;
Sinyaller geçmiş sinyallerin 15/30/60/120 dakika, gün sonu, MFE ve MAE sonuçlarını gösterir. Sonuç
oluşmadıysa sıfır uydurulmaz. Portföy açık/kapalı paper işlemleri seviyeleriyle gösterir; MTM fiyatı
yoksa gerçekleşmemiş kâr/zarar üretilmez. Analiz ekranı ham JSON yerine örneklem sayılı skor kartları
kullanır.

## Production hygiene ve sunum sınırları

Production paper portföyü yalnız `paper-default` portföyü ile
`radar-intraday-v1` strateji bağlamını gösterir. Acceptance, fixture ve replay
kayıtları ayrı context'te tutulur; testler izole veritabanı kullanır. Radar aday
aggregation'ı canonical sembol başına yalnız en yeni gözlemi seçer ve eşit
puanlarda sembol sırasıyla deterministik davranır.

Backend enumları audit amacıyla korunur; snake_case ve internal hesaplama
tanımları kullanıcıya gösterilmez. Piyasa kapalı veya veri eskiyse plan durumu
“son tamamlanmış veriye göre” bağlamıyla sunulur. Grafik alım bölgesini bant;
stop, hedefler ve referans fiyatı etiketli seviyeler olarak gösterir. Backend
EMA/VWAP serisi sağlamadığında arayüz sahte gösterge çizgisi üretmez.
