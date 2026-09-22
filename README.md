# PropVision

PropVision es un MVP local para simular evaluaciones de prop firms con Monte Carlo y comparar combinaciones de TP/SL/reset/price.

## Requisitos

- Python 3.11+
- pip

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

En macOS/Linux, activa el entorno con `source .venv/bin/activate`.

## Variables de entorno

Copia `.env.example` a `.env` y añade tus credenciales de Supabase si quieres cargar cuentas reales:

```bash
copy .env.example .env
```

En macOS/Linux, usa `cp .env.example .env`. El archivo `.env` es local y no debe subirse al repositorio.

La aplicación necesita `SUPABASE_URL` y `SUPABASE_KEY` para iniciar la conexión con la base de datos.

## Ejecutar la app

```bash
streamlit run app.py
```

## Probar el motor

```bash
pytest -q
```
