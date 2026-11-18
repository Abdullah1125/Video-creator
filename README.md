# 🎬 Çocuk Video Stüdyosu

Konuyu, dili ve tasarım tarzını veriyorsun; **Claude** çocuklara uygun kısa bir hikaye yazıyor,
her sahneyi kendi çiziyor (ayrı bir ücretli görsel-üretim API'si yok), sonra açık kaynak
[**purffle-shorts**](https://github.com/Chamanrajragu/purffle-shorts) motoru seslendirme, altyazı
ve video birleştirmeyi yapıp elinde bitmiş bir MP4 bırakıyor.

Mobil tarayıcıdan kullanılabilen tek sayfalık bir arayüzü var: konu, dil, tasarım tarzı, yön
(dikey/yatay) ve süre seç, "Videoyu Oluştur"a bas, ilerlemeyi izle, videoyu izle/indir.

## Nasıl çalışıyor

```
Konu + Dil + Tasarım tarzı
        │
        ├─ 1. Claude hikayeyi yazar (sahne sahne, seçilen dilde, çocuklara uygun)
        ├─ 2. Claude her sahneyi SVG olarak çizer (seçilen tarzda) → PNG'ye dönüştürülür
        ├─ 3. purffle-shorts: seslendirme (ücretsiz, 75+ dil), kelime zamanlı altyazı
        └─ 4. ffmpeg ile son video birleştirilir → indirilebilir MP4
```

## Kurulum (kendi bilgisayarında / sunucunda, Docker ile)

1. Bu depoyu klonla ve içine gir.
2. `.env.example` dosyasını `.env` olarak kopyala ve **ANTHROPIC_API_KEY**'ini yaz
   (anahtarı [console.anthropic.com](https://console.anthropic.com/settings/keys)'dan alabilirsin).
3. Başlat:

   ```bash
   docker compose up --build
   ```

4. Telefonundan veya bilgisayarından, aynı ağdaysan `http://<sunucu-ip>:8000` adresini aç.
   Sadece kendi bilgisayarındaysan `http://localhost:8000`.

Dışarıdan (ev ağın dışından) telefondan erişmek istersen, sunucunu bir ters-proxy / tünel
(örn. Tailscale, Cloudflare Tunnel, ya da gerçek bir alan adı + HTTPS) arkasına koyman gerekir —
bu depo kasıtlı olarak sade tutuldu, dilersen bunu birlikte ekleyebiliriz.

## Docker'sız çalıştırma

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ANTHROPIC_API_KEY'i doldur
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`ffmpeg` ve (sahne illüstrasyonlarını PNG'ye çevirmek için) sistemde `libcairo2` kurulu olmalı
(macOS: `brew install ffmpeg cairo`, Debian/Ubuntu: `apt install ffmpeg libcairo2`).

## Yapı

```
app/
  main.py        FastAPI sunucusu: form, iş (job) durumu, video indirme
  pipeline.py     Claude ile senaryo + sahne illüstrasyonu, purffle-shorts render çağrısı
  templates/      Mobil uyumlu tek sayfa arayüz
  static/         CSS + JS (ilerleme çubuğu, video oynatıcı)
jobs/             Her video için ayrı klasör (sahne PNG'leri, script.json, bitmiş MP4)
```

## Neden purffle-shorts?

[PurffleShorts](https://github.com/Chamanrajragu/purffle-shorts) MIT lisanslı, aktif geliştirilen,
Claude dahil 12 LLM sağlayıcısını destekleyen, 75+ dilde ücretsiz seslendirme yapan, kelime
zamanlı altyazı ekleyen ve Docker ile çalışan olgun bir video üretim motoru. Bu proje onun kendi
senaryo-yazma ve görsel-üretim adımlarını **atlayıp**, bunların yerine Claude'un yazdığı
çocuklara özel senaryoyu ve Claude'un çizdiği sahne illüstrasyonlarını "yerel görsel" (`local`
visual source) olarak ona veriyor; seslendirme, altyazı ve render işini olduğu gibi ondan alıyor.

## Güvenlik notu

Senaryo isteminde (prompt) çocuklara uygunluk zorunlu tutuldu: korku/şiddet yok, gerçek kişiler
yok, her hikaye olumlu bitiyor. Yine de yayınlamadan önce bitmiş videoyu bir yetişkinin izlemesi
önerilir — hiçbir otomatik sistem %100 garanti vermez.
