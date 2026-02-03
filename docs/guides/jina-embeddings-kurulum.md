# Jina Embeddings v3 Yerel Kurulum ve Entegrasyon

Bu döküman, **jinaai/jina-embeddings-v3** modelini `mcp-code-intelligence` ile nasıl kullanacağınızı açıklar.

## 🚀 Jina v3 Özellikleri

- **Hem Kod Hem Dil:** Jina v3, sadece metin değil, kod yapılarını (semantic coding) anlamak için özel olarak eğitilmiştir.
- **8192 Bağlam:** Çok uzun dosyaları bile parçalamadan görebilir.
- **Tam Uyumluluk:** `sentence-transformers` kütüphanesi ile %100 uyumludur.

## 🛠️ Kurulum ve Geçiş

### 1. Dosya Yapılandırması
Sistemin Jina v3'ü tanıması için gerekli dosya değişiklikleri yapıldı ve `einops` kütüphanesi yüklendi.

### 2. İndeksi Yenileme
Model değişimi sonrası eski indeksler geçersizdir. Aşağıdaki komutla indeksi yenileyin:

```bash
mcp-code-intelligence index --force
```

### 3. Önemli Parametreler
Kodda `trust_remote_code=True` otomatik olarak aktifleştirilmiştir, bu sayede modelin özel katmanları sorunsuz yüklenir.

## 🔍 Model Hakkında Not
Daha önce denenen v2-multilingual modelinin teknik uyumsuzlukları nedeniyle, Jina'nın amiral gemisi olan v3 modeline geçilmiştir. Bu model hem Türkçe dokümanlarınızda hem de programlama dillerinde v2'den daha yüksek performans sergiler.

---
*Daha fazla bilgi için ana [README.md](../../README.md) dosyasını inceleyebilirsiniz.*

