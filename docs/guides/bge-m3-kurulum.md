# BAAI/bge-m3 Yerel Kurulum ve VS Code Entegrasyonu

Bu döküman, endüstri lideri çok dilli (multilingual) model olan **BAAI/bge-m3**'ü yerel olarak kurup `mcp-code-intelligence` ile VS Code (Roo Code/Cline) üzerinde nasıl kullanacağınızı adım adım açıklar.

## 🚀 Neden BGE-M3?

- **Multilingual Kapasite:** Türkçe dahil 100'den fazla dilde yüksek doğruluk.
- **Yerel ve Ücretsiz:** Kodunuz bilgisayarınızdan çıkmaz, API maliyeti yoktur.
- **Yüksek Boyutlu Bağlam:** 8192 token'a kadar girdi desteği (kod blokları için ideal).

## 🛠️ Kurulum Adımları

### 1. Python Ortamını Hazırlayın
Eğer `mcp-code-intelligence` kurulu değilse, önce onu ve gerekli kütüphaneleri yükleyin:

```bash
# Proje dizinine gidin
pip install mcp-code-intelligence
pip install torch sentence-transformers
```

### 2. Modeli Yapılandırın
**Artık `BAAI/bge-m3` varsayılan model olarak ayarlanmıştır.** Yeni bir proje başlatıyorsanız herhangi bir ayar yapmanıza gerek yoktur. Mevcut bir projede geçiş yapmak için:

```bash
mcp-code-intelligence config set embedding_model BAAI/bge-m3
```

> [!TIP]
> `bge-m3` modeli artık otomatik olarak `normalize_embeddings=True` parametresiyle çalışarak en yüksek performansı verecek şekilde optimize edilmiştir.

### 3. İndeksleme İşlemini Başlatın
Projenizi yeni model ile tarayın:

```bash
mcp-code-intelligence index --force
```

### 4. VS Code (Roo Code / Cline) Entegrasyonu
VS Code içindeki MCP ayarlarınıza aşağıdaki sunucuyu ekleyin veya `mcp-code-intelligence setup` komutunu kullanın:

**Manuel Ekleme (MCP Config):**
```json
{
  "mcpServers": {
    "vector-search": {
      "command": "uv",
      "args": ["run", "python", "-m", "mcp_code_intelligence.mcp.server", "C:/PROJE/DIZININIZ"],
      "env": {
        "MCP_ENABLE_FILE_WATCHING": "true"
      }
    }
  }
}
```

## 🔍 Kullanım İpuçları

- **Daha İyi Sonuçlar İçin:** Arama yaparken teknik terimlerin yanına Türkçe açıklamalar ekleyebilirsiniz (Örn: "authentication logic - kullanıcı giriş doğrulama").
- **Performans:** İlk indeksleme modelin büyüklüğü nedeniyle biraz zaman alabilir, ancak sonraki aramalar milisaniyeler içinde sonuçlanacaktır.

---
*Daha fazla bilgi için ana [README.md](../../README.md) dosyasını inceleyebilirsiniz.*


