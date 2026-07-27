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

## Variables de entorno

Copia .env.example a .env y añade tus credenciales de Supabase si quieres cargar cuentas reales:

```bash
copy .env.example .env
```

## Ejecutar la app

```bash
streamlit run app.py
```

## Probar el motor

```bash
pytest -q
```
