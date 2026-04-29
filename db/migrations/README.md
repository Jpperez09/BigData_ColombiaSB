# Setup de Supabase — Guía para el equipo

Instrucciones paso a paso para crear el proyecto Supabase y dejar la DB lista para recibir datos scrapeados.

---

## 1. Crear el proyecto en Supabase

1. Ve a [supabase.com](https://supabase.com) e inicia sesión (o crea cuenta gratis).
2. Haz clic en **"New project"**.
3. Elige la organización, ponle nombre al proyecto (ej. `big-data-final`) y escoge una contraseña segura para el DB.
4. En **Region**, selecciona **South America (São Paulo)** si está disponible — reduce latencia desde Colombia.
   Si no aparece, usa **US East (N. Virginia)** como segunda opción.
5. Haz clic en **"Create new project"** y espera ~2 minutos hasta que el dashboard diga "Project is ready".

---

## 2. Abrir el SQL Editor

1. En el panel izquierdo del proyecto, haz clic en el ícono de **"SQL Editor"** (parece una terminal `>_`).
2. Haz clic en **"New query"** para abrir una pestaña en blanco.

---

## 3. Correr la migración `001_create_schema.sql`

1. Abre el archivo `db/migrations/001_create_schema.sql` en tu editor de código.
2. Selecciona **todo** el contenido (Ctrl+A) y cópialo (Ctrl+C).
3. Pégalo en el SQL Editor de Supabase (Ctrl+V).
4. Haz clic en el botón **"RUN"** (o presiona Ctrl+Enter).
5. Verás `Success. No rows returned` al fondo — eso es correcto y esperado.

> **Idempotente:** el script usa `IF NOT EXISTS` y `ON CONFLICT DO NOTHING`, así que puedes correrlo múltiples veces sin riesgo.

---

## 4. Obtener el `service_role` key y configurar `.env`

1. En el panel izquierdo, ve a **Project Settings** (ícono de engranaje) → **API**.
2. En la sección **"Project URL"**, copia la URL (formato `https://xxxxxxxxxxxx.supabase.co`).
3. En la sección **"Project API keys"**, copia la key que dice **`service_role`**.
   ⚠️ **NO uses la key `anon`** — esa es para clientes públicos y no tiene permisos de escritura total.
4. Crea (o edita) el archivo `.env` en la raíz del repositorio:

```env
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

> **Seguridad:** `.env` ya está en `.gitignore`. Nunca lo subas al repositorio.

---

## 5. Query de validación

Corre esto en el SQL Editor para confirmar que las 3 tablas existen y que `sources` tiene exactamente 4 filas:

```sql
SELECT 'sources'               AS tabla, COUNT(*) AS filas FROM sources
UNION ALL
SELECT 'businesses_raw',                 COUNT(*)           FROM businesses_raw
UNION ALL
SELECT 'businesses_canonical',           COUNT(*)           FROM businesses_canonical;
```

**Resultado esperado:**

| tabla                 | filas |
|-----------------------|-------|
| sources               | 4     |
| businesses_raw        | 0     |
| businesses_canonical  | 0     |

Para ver los sources registrados:

```sql
SELECT id, name, description FROM sources ORDER BY id;
```

**Esperado:** `gmaps`, `instagram`, `paginas_amarillas`, `mercado_libre`.

Si ves 4 filas en `sources` y 0 en las tablas de negocio → migración exitosa. ✓

---

## 6. Verificar que el loader funciona (dry-run)

Sin necesidad de credenciales, puedes validar un parquet de prueba:

```bash
python -m utils.load_to_supabase \
  --source gmaps \
  --path data/raw/gmaps/medellin.parquet \
  --dry-run
```

El flag `--dry-run` valida los datos contra el schema Pydantic pero **no toca Supabase**. Útil para confirmar que un parquet está bien formado antes de insertarlo.
