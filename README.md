# BIST Radar

Professional research/paper-trading decision support for BIST, including deterministic daily and
intraday Radar, outcome intelligence, shadow learning, a Turkish mobile-first web dashboard, and
optional Telegram alerts. It never sends a real order.

Dashboard: `http://127.0.0.1:8770`

API: `http://127.0.0.1:8765`

Both are localhost-only. See [dashboard](docs/dashboard.md), [Telegram](docs/telegram.md), and
[autonomous operations](docs/operations.md). Yahoo/yfinance data is unofficial, unverified,
research-only data and is not suitable for production/live-trading validation.

Cloudflare publication readiness and the mandatory Access boundary are documented in
[Cloudflare Tunnel publication](docs/cloudflare-access.md). Public publication remains disabled
until the remotely managed tunnel and Access policy are configured with authorized credentials.

BIST hisseleri için açıklanabilir karar-destek, tarama, backtest ve paper-trading sistemi. Gerçek emir göndermez; `TRADING_MODE=live` başlangıçta reddedilir.

## Mimari ve güvenlik

Akış: Provider → doğrulama/kalite → özellikler → piyasa rejimi → Radar Score → risk → sinyal → paper ledger → bildirim. Ham veri doğrulanmadan skora girmez. Eski, çelişkili, eksik veya düşük kaliteli veri; geçersiz stop ya da 2.0 altı R/R `NO_SIGNAL` üretir. UTC saklanır, sunum takviminde `Europe/Istanbul` hedeflenir. AI sayısal hesaplarda kullanılmaz.

## Kurulum

Python 3.11 ile geliştirme uyumludur; container Python 3.12 kullanır.

```bash
make install
make seed
make check
cp .env.example .env  # güçlü bir POSTGRES_PASSWORD belirleyin
docker compose up -d --build
curl http://127.0.0.1:8765/health
```

Compose yalnızca `bist-radar-network` ve `bist-radar-postgres-data` oluşturur. API sadece loopback'te yayınlanır. Port doluysa `.env` içinde `API_PORT` değiştirin. `make down` yalnızca bu compose projesini durdurur ve volume silmez.

## Yapılandırma

Tüm örnekler `.env.example` dosyasındadır. Varsayılanlar: veri kalitesi 90, risk/işlem %0.75, minimum R/R 2.0, komisyon 10 bps, slippage 5 bps. Secret'lar `.env` içinde kalır ve loglanmaz.

## API

`GET /health`, `/ready`, `/symbols`, `/radar`, `/radar/{symbol}`, `/signals`, `/paper/trades`, `/paper/performance`, `/system/status`. Yanıtlarda paper-mode ve yatırım tavsiyesi olmadığı vurgulanır. Swagger: `/docs`.

Paper trade ledger PostgreSQL üzerinde kalıcıdır. `active_symbol` unique constraint'i aynı sembolde yalnız bir açık işleme izin verir; repository işlemleri transaction içinde atomik çalışır. API restart kayıtları kaybettirmez.

## Historical replay

Replay motoru OHLCV verisini kronolojik olarak bar-bar ilerletir ve stratejiye yalnız o ana kadar görünür olan pencereyi verir. Sinyal `t` kapanışında oluşur, giriş varsayılan olarak `t+1 OPEN` fiyatındadır. Entry gap limiti aşılırsa işlem reddedilir. Aynı barda stop ve hedef görülürse muhafazakâr `STOP_FIRST` uygulanır; stop altı açılış gerçek open fiyatından fill edilir. Portfolio pozisyon/risk limitleri, commission ve slippage uygulanır. Replay run, immutable config hash, audit kayıtları, trade ve equity curve PostgreSQL'de kalıcıdır.

Endpointler: `POST /replay`, `GET /replay/{run_id}`, `/trades`, `/performance`, `/equity`. API yalnız loopback binding'ini korur.

## Provider ekleme

Piyasa verisi için `MarketDataProvider`, KAP için `KapProvider`, takas için `TakasProvider` sınıfını uygulayın ve dependency injection ile servise verin. HTML scraping production sağlayıcısı değildir. Licensed provider ağ hatalarında sınırlı retry/backoff uygulamalı, sonra `PROVIDER_DOWN` dönmelidir. İkinci piyasa kaynağı fiyat toleransı aşınca `DATA_CONFLICT` üretmelidir. KAP ham metni değişmeden saklanır; takas yoksa `TAKAS_DATA_UNAVAILABLE` normal durumdur.

Telegram token yokken `MockTelegramNotifier` kullanılır. Gerçek entegrasyon eklendiğinde token yalnız environment'tan alınmalı.

Ücretsiz historical research akışı `YFinanceResearchProvider` ile sağlanır. Bu resmi Borsa
İstanbul verisi değildir; `RESEARCH_ONLY` ve `UNVERIFIED_SOURCE` olarak etiketlenir ve
production/live doğrulamada kullanılamaz. Dry-run, cache, survivorship bias ve frozen dataset
iş akışı için [docs/free-research-data.md](docs/free-research-data.md) belgesine bakın.

## Demo ve test

Deterministik `rally`, `flat`, `selloff`, `bad_data` ve `xu100` fixture'ları bulunur. `make check` format, Ruff, mypy, pytest ve coverage kapısını çalıştırır. Backtest sinyali kapanış `t` ile hesaplar ve girişi `t+1` açılışında yapar. Evren geçmişi sağlanmadan survivorship-bias ortadan kaldırılamaz; raporlarda bu kısıt belirtilmelidir. Split/temettü ayarı provider metadata'sıyla doğrulanmalıdır.

## Troubleshooting

- Başlangıçta live-mode hatası: `.env` içinde `TRADING_MODE=paper` yapın.
- DB hazır değil: `docker compose logs bist-radar-db`, sonra migration çalıştırın.
- Provider yok: fixture modu çalışmaya devam eder; bu production piyasa verisi değildir.
- Port çakışması: `ss -ltn` ile kontrol edip `API_PORT` değiştirin.

Bu sistem yatırım tavsiyesi değildir. Karar-destek ve paper trading amaçlıdır.
