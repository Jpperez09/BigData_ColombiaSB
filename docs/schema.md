# Canonical Data Schema — Businesses

## Overview

Una fila por business **por fuente** en `businesses_raw`. Cada scraper (Google Maps, Instagram, directorios) inserta sus filas de forma independiente; la misma empresa física puede tener hasta N filas en `businesses_raw`, una por source. La deduplicación cross-source ocurre en Step 2 via `master_id` y produce `businesses_canonical` (una fila por `master_id`, con el mejor representante de cada campo según las reglas de merge definidas más abajo).

---

## Tablas

### `businesses_raw`
Staging table. Una fila por `(source, source_id)`. Acepta data sucia — normalizaciones parciales, nulls, formatos inconsistentes. Esta tabla **nunca se trunca**; es el registro histórico completo de scraping.

| Propiedad | Valor |
|-----------|-------|
| Clave de unicidad | `(source, source_id)` |
| Escritura | Scrapers (Juanpa + Leo) |
| Lectura | Step 2 (entity resolution + cleaning) |

### `businesses_canonical`
Una fila por `master_id`, producida y mantenida por Step 2. Misma estructura que `businesses_raw` más `master_id NOT NULL`. Es la tabla que consume el dashboard y el scoring.

| Propiedad | Valor |
|-----------|-------|
| Clave primaria lógica | `master_id` |
| Escritura | Pipeline Step 2 solamente |
| Lectura | Dashboard, scoring, exports |

### `sources`
Lookup table de fuentes conocidas. Evita typos en el campo `source`.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | serial | PK interno |
| `name` | text | Identificador canónico de la fuente |
| `description` | text | Descripción humana |

**Valores válidos de `name`:** `gmaps` · `instagram` · `paginas_amarillas` · `mercado_libre`

---

## Diccionario de campos — `businesses_raw`

| Campo | Tipo | Nullable | Descripción | Ejemplo | Fuente típica |
|-------|------|----------|-------------|---------|---------------|
| `id` | uuid | NO | PK, generado automáticamente | `a1b2c3d4-...` | — |
| `master_id` | uuid | SÍ | FK a `businesses_canonical`. Null hasta Step 2 | `f9e8d7c6-...` | Step 2 |
| `source` | text | NO | Fuente de la fila, FK a `sources.name` | `gmaps` | Scraper |
| `source_id` | text | NO | ID original de la fuente | `ChIJN1t_tDeuEmsRUsoyG83frY4` | Scraper |
| `name` | text | NO | Nombre del negocio tal como aparece en la fuente | `Pastelería Los Andes S.A.S.` | Scraper |
| `name_normalized` | text | SÍ | lowercase, sin tildes, sin sufijos legales (S.A.S., Ltda., S.A., E.U., Corp.) | `pasteleria los andes` | Scraper o Step 2 |
| `address_raw` | text | SÍ | Dirección completa sin parsear | `Cra 45 # 53-24, El Poblado, Medellín` | gmaps, directorios |
| `address_street` | text | SÍ | Sólo calle/carrera y número | `Cra 45 # 53-24` | gmaps, directorios |
| `city` | text | NO | Ciudad, valores canónicos solamente | `Medellín` | Scraper |
| `neighborhood` | text | SÍ | Barrio o sector | `El Poblado` | gmaps, directorios |
| `lat` | double precision | SÍ | Latitud WGS-84 | `6.2086` | gmaps |
| `lng` | double precision | SÍ | Longitud WGS-84 | `-75.5672` | gmaps |
| `phone_raw` | text | SÍ | Teléfono tal como aparece en la fuente | `604 311 2200` | gmaps, directorios |
| `phone_e164` | text | SÍ | Teléfono normalizado E.164 Colombia | `+576043112200` | Step 2 / scraper |
| `whatsapp_flag` | boolean | NO | True si el teléfono está marcado como WhatsApp en la fuente o si aparece link `wa.me` | `true` | gmaps, instagram |
| `instagram_handle` | text | SÍ | Usuario de Instagram sin `@` | `pasteleria_andes` | instagram, gmaps |
| `instagram_followers` | integer | SÍ | Seguidores al momento del scrape | `4820` | instagram |
| `instagram_posts_count` | integer | SÍ | Total de publicaciones | `213` | instagram |
| `instagram_last_post_at` | timestamptz | SÍ | Timestamp del post más reciente | `2024-03-15T14:22:00Z` | instagram |
| `instagram_has_catalog` | boolean | SÍ | True si el perfil tiene catálogo de productos activo | `false` | instagram |
| `category_raw` | text | SÍ | Categoría tal como aparece en la fuente | `Panadería y pastelería` | gmaps, directorios |
| `ciiu_code` | text | SÍ | Código CIIU asignado en Step 2 (no scrapeado) | `1081` | Step 2 |
| `rating` | numeric(2,1) | SÍ | Calificación promedio 0–5 | `4.3` | gmaps |
| `reviews_count` | integer | SÍ | Número de reseñas | `127` | gmaps |
| `website` | text | SÍ | URL del sitio web | `https://pasteleria-andes.com` | gmaps, directorios |
| `bio_text` | text | SÍ | Descripción/bio del negocio | `"Pasteles artesanales desde 1998..."` | instagram, gmaps |
| `quality_flags` | jsonb | NO | Array de strings indicando problemas de calidad detectados | `["missing_phone", "low_confidence_address"]` | Scraper / Step 2 |
| `scraped_at` | timestamptz | NO | Momento en que el scraper recolectó el registro | `2024-04-01T10:30:00Z` | Scraper |
| `created_at` | timestamptz | NO | Inserción en DB (default `now()`) | `2024-04-01T10:31:00Z` | DB |
| `updated_at` | timestamptz | NO | Última modificación (actualizado por trigger) | `2024-04-01T10:31:00Z` | DB trigger |

**Valores válidos de `quality_flags`:**

| Flag | Significado |
|------|-------------|
| `missing_phone` | No se encontró ningún teléfono |
| `missing_address` | Sin dirección |
| `low_confidence_address` | Dirección incompleta o ambigua |
| `unverified_coordinates` | Coords derivadas de geocoding, no de la fuente |
| `inactive_instagram` | Último post hace > 6 meses |
| `duplicate_candidate` | Posible duplicado detectado en Step 2 |

---

## Reglas de merge para Step 2

Cuando múltiples filas de `businesses_raw` se agrupan bajo un mismo `master_id`, el campo ganador para `businesses_canonical` se determina así:

| Campo | Fuente ganadora | Criterio de desempate |
|-------|-----------------|-----------------------|
| `name` | `gmaps` | Si null → directorios → instagram |
| `name_normalized` | Derivado de `name` ganador | Aplicar normalización estándar |
| `address_raw` | `gmaps` | Si null → `paginas_amarillas` → `mercado_libre` |
| `address_street` | `gmaps` | Si null → directorios |
| `city` | Cualquier fuente | Todos deben concordar; si difieren, `gmaps` gana |
| `neighborhood` | `gmaps` | Si null → directorios |
| `lat` / `lng` | `gmaps` | Siempre; directorios solo si gmaps es null |
| `phone_raw` | `gmaps` | Si null → `paginas_amarillas` → `mercado_libre` |
| `phone_e164` | `gmaps` | Si null → `paginas_amarillas` → `mercado_libre` |
| `whatsapp_flag` | `gmaps` o `instagram` | OR lógico: true si cualquier fuente lo marca |
| `instagram_handle` | `instagram` | Si null → `gmaps` (si gmaps lo tiene en el perfil) |
| `instagram_followers` | `instagram` | Siempre; gmaps no tiene este dato |
| `instagram_posts_count` | `instagram` | Siempre |
| `instagram_last_post_at` | `instagram` | Siempre |
| `instagram_has_catalog` | `instagram` | Siempre |
| `category_raw` | `gmaps` | Si null → directorios |
| `ciiu_code` | Step 2 | Asignado post-merge, no viene de scrapers |
| `rating` | `gmaps` | Siempre; instagram no tiene rating numérico equivalente |
| `reviews_count` | `gmaps` | Siempre |
| `website` | `gmaps` | Si null → directorios → instagram |
| `bio_text` | `instagram` | Si null → `gmaps` (editorial summary) |
| `quality_flags` | Unión de todos | Merge de todos los arrays de todas las fuentes |
| `scraped_at` | El más reciente | `MAX(scraped_at)` entre todas las fuentes |

---

## Índices necesarios

| Índice | Tipo | Tabla | Justificación |
|--------|------|-------|---------------|
| `UNIQUE (source, source_id)` | btree | `businesses_raw` | Previene duplicados del mismo scraper; clave de upsert |
| `idx_raw_master_id` | btree | `businesses_raw` | JOIN frecuente en Step 2 para agrupar por entidad |
| `idx_raw_city` | btree | `businesses_raw` | Filtros por ciudad en toda consulta analítica |
| `idx_raw_ciiu_code` | btree | `businesses_raw` | Segmentación por sector en scoring y dashboard |
| `idx_raw_name_normalized_trgm` | GIN trigram | `businesses_raw` | Fuzzy matching en Step 2 (entity resolution basado en nombre) |
| `idx_raw_phone_e164` | btree | `businesses_raw` | Deduplicación exacta por teléfono en Step 2 |
| `idx_canonical_master_id` | btree (PK lógica) | `businesses_canonical` | Lookup por entidad desde dashboard y scoring |
| `idx_canonical_city` | btree | `businesses_canonical` | Filtros de ciudad en queries de producción |
| `idx_canonical_ciiu_code` | btree | `businesses_canonical` | Segmentación sectorial en producción |
| `idx_canonical_name_normalized_trgm` | GIN trigram | `businesses_canonical` | Búsqueda fuzzy en UI del dashboard |
| `idx_canonical_phone_e164` | btree | `businesses_canonical` | Lookup de contacto único |
