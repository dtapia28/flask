# Checklist familiar

Aplicación Flask en español para listas asignadas, cumplimiento diario e historial. Zona de negocio: `America/Santiago`. Roles: administrador y usuario.

## Ejecutar localmente (Mac / VS Code)

1. Abre esta carpeta en VS Code y crea un entorno: `python3 -m venv .venv && source .venv/bin/activate`.
2. Instala paquetes: `pip install -r requirements.txt`.
3. Copia `.env.example` a `.env`, genera `SECRET_KEY` y `CRON_SECRET` con `python -c "import secrets; print(secrets.token_hex(32))"`. La aplicación carga `.env` y `.flaskenv` con el mismo cargador de Flask CLI, tanto con `python main.py` como con `flask --app main run`; las variables exportadas en la terminal prevalecen.
4. Aplica las migraciones incluidas en el repositorio: `flask --app main db upgrade`. Usa la misma carpeta y el mismo `.env` para migrar y arrancar Flask; así ambos comandos apuntan a la misma `DATABASE_URL`.
5. Crea el primer administrador: `flask --app main create-admin` (ver abajo).
6. Ejecuta `python main.py` y abre `http://localhost:5000`.

## Administrador inicial

Después de aplicar `flask --app main db upgrade`, y con `SECRET_KEY` y `DATABASE_URL` ya configuradas, ejecuta `flask --app main create-admin`. La revisión `8c4fd62b7a10` repara bases que tienen la versión Alembic avanzada pero les faltan tablas, preservando tablas y datos existentes. Si aparece “no such table: user”, ejecuta `flask --app main db upgrade` desde la raíz del proyecto y vuelve a crear el administrador; si no aplica revisiones, comprueba que ambos comandos usan el mismo `.env` y `DATABASE_URL`. El comando solicita nombre, correo y contraseña mediante entrada oculta; exige al menos 8 caracteres, no hay credenciales por defecto ni registro público. Los enlaces de invitación y recuperación también exigen 8 caracteres. Para añadir integrantes, usa Administración y comparte el enlace de invitación de un solo uso, válido dos horas.

## Correo y evaluación de cierres

Desarrollo usa `MAIL_MODE=console`: los mensajes quedan registrados y se escriben en el log local, sin entregarse. Producción requiere `MAIL_MODE=smtp`, `MAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, y `ADMIN_EMAIL`. SMTP debe permitir STARTTLS.

Cierres/envíos se procesan mediante `POST /admin/cron` con `Authorization: Bearer $CRON_SECRET`. Configura un cron externo de bajo costo para llamar el endpoint, idealmente cada 5–15 minutos. Repetirlo es seguro por claves únicas de correo. Los cierres atrasados se generan con su fecha local real y el correo al usuario se agrupa por usuario y fecha. El servicio de cron debe reintentar errores HTTP; los errores de entrega quedan en el log del servicio. La ruta puede tardar según el volumen de fechas acumuladas.

## Railway

- Añade una base PostgreSQL persistente y asigna su `DATABASE_URL` al servicio Flask. SQLite local sirve solo para desarrollo: el disco de Railway no debe considerarse persistente.
- Define `SECRET_KEY`, `COOKIE_SECURE=true`, `APP_URL=https://tapiaaraya.com/checklist`, `CRON_SECRET`, `MAIL_MODE=smtp`, credenciales SMTP y `ADMIN_EMAIL`.
- Ejecuta `flask --app main db upgrade` en el proceso de release antes de iniciar Gunicorn (`gunicorn main:app`). Programa el POST autenticado a `/admin/cron` desde el cron que elijas.
- No se ha publicado ni modificado Railway.

## Pruebas

Ejecuta `python -m pytest -q` para validar permisos, persistencia, cierres de Santiago, deduplicación de correos, rachas de siete días, snapshots históricos, enlaces de un solo uso y autenticación del cron.

## Migraciones

Se usa Flask-Migrate/Alembic. Para nueva versión: `flask --app main db migrate -m "descripcion"`, revisar el archivo generado en `migrations/versions/` y aplicar con `flask --app main db upgrade`.

## Alcance actual y notas

Las tareas se congelan en el primer registro diario creado, preservando días cerrados cuando cambien tareas. Usuarios pueden ver y completar sus asignaciones, el servidor aplica el aislamiento y bloquea cambios después del cierre. Administradores gestionan usuarios (activar/desactivar), listas nuevas con tantas secciones de elementos como necesites, asignaciones, pausas y correcciones con motivo; pueden consultar historial de cumplimiento/correos. En esta primera versión las listas son inmutables desde interfaz tras crearse para proteger historial; para cambiar contenido, crea una lista revisada y asígnala. El filtro de cumplimiento permite seleccionar usuario, lista y rango de fechas. Si activas el aviso semanal en una asignación ya creada, su conteo comienza ese día.
