# Checklist familiar

Aplicación Flask en español para listas asignadas, cumplimiento diario e historial. Zona de negocio: `America/Santiago`. Roles: administrador y usuario.

## Ejecutar localmente (Mac / VS Code)

1. Abre esta carpeta en VS Code y crea un entorno: `python3 -m venv .venv && source .venv/bin/activate`.
2. Instala paquetes de desarrollo: `pip install -r requirements-dev.txt`.
3. Copia `.env.example` a `.env`, genera `SECRET_KEY` y `CRON_SECRET` con `python -c "import secrets; print(secrets.token_hex(32))"`. La aplicación carga `.env` y `.flaskenv` con el mismo cargador de Flask CLI, tanto con `python main.py` como con `flask --app main run`; las variables exportadas en la terminal prevalecen.
4. Aplica las migraciones incluidas en el repositorio: `flask --app main db upgrade`. Usa la misma carpeta y el mismo `.env` para migrar y arrancar Flask; así ambos comandos apuntan a la misma `DATABASE_URL`.
5. Crea el primer administrador: `flask --app main create-admin` (ver abajo).
6. Ejecuta `python main.py` y abre `http://localhost:5000`.

## Datos de prueba locales

Para cargar cuentas demo y una lista asignada sin contraseñas fijas, ejecuta las migraciones y luego activa el comando solo para esa llamada:

```bash
flask --app main db upgrade
ALLOW_DEMO_SEED=true APP_URL=http://localhost:5001 flask --app main seed-demo
```

El comando solo acepta SQLite local, se niega en Railway/producción, es idempotente y muestra enlaces de establecimiento de contraseña de un solo uso, válidos por dos horas. Puedes cambiar `DEMO_ADMIN_EMAIL` y `DEMO_USER_EMAIL` en `.env`. No se ejecuta al arrancar la app ni borra datos.

## Administrador inicial

Después de aplicar `flask --app main db upgrade`, y con `SECRET_KEY` y `DATABASE_URL` ya configuradas, ejecuta `flask --app main create-admin`. Las revisiones de reparación reconcilian bases SQLite cuyo marcador Alembic avanzó pero quedaron con tablas incompletas tras un fallo DDL, preservando tablas y datos existentes. Si aparece “no such table: user”, ejecuta `flask --app main db upgrade` desde la raíz del proyecto y vuelve a crear el administrador; si no aplica revisiones, comprueba que ambos comandos usan el mismo `.env` y `DATABASE_URL`. El comando solicita nombre, correo y contraseña mediante entrada oculta; exige al menos 8 caracteres, no hay credenciales por defecto ni registro público. Los enlaces de invitación y recuperación también exigen 8 caracteres. Para añadir integrantes, usa Administración y comparte el enlace de invitación de un solo uso, válido dos horas.

## Correo y evaluación de cierres

Desarrollo usa `MAIL_MODE=console`: no envía correo y oculta enlaces temporales en el log. En producción se recomienda `MAIL_MODE=zeptomail`, que envía por HTTPS. Requiere `MAIL_FROM` con un remitente verificado en ZeptoMail, `ZEPTOMAIL_API_KEY` (Send API key del Agent) y `ADMIN_EMAIL`. Verifica el dominio emisor y genera la clave en ZeptoMail → Agent → SMTP/API → API. El endpoint predeterminado es `https://cpaas.zoho.com/v1.1/email`; define `ZEPTOMAIL_API_URL` solo si tu cuenta usa otra región. La API tiene timeout de cinco segundos. Como alternativa en entornos que permitan SMTP, `MAIL_MODE=smtp` usa `MAIL_FROM`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` y STARTTLS con timeout de cinco segundos. Consulta la [documentación oficial de envío por API de ZeptoMail](https://www.zoho.com/cpaas/help/api/email-sending.html).

Una invitación fallida deja al usuario guardado y una fila `failed` o `pending` en el historial de correo. En Administración → Usuarios, el administrador puede **Reenviar invitación** o **Generar nuevo enlace** manualmente sin esperar al correo. Como solo se almacena el hash del token, no se puede recuperar el enlace original: el botón invalida tokens anteriores, crea uno nuevo de un solo uso con vencimiento de dos horas y lo copia al portapapeles; si el navegador lo bloquea, queda seleccionado en un campo. El enlace se devuelve solo al administrador que lo pidió y nunca se guarda en los logs. El reenvío por email conserva la misma cuenta. Para distinguir usuarios que aún no establecen contraseña, la migración añade `user.password_configured` y clasifica las cuentas existentes usando sus tokens previos.

Cierres/envíos se procesan con `flask --app main process-closures`, que cierra los registros vencidos, manda los correos configurados y termina. Programa una ejecución cada 5 minutos en el servicio cron de Railway. El comando también puede ejecutarse manualmente en local. El endpoint autenticado `POST /admin/cron` sigue disponible para un cron HTTP externo. Los cierres atrasados usan la fecha local real; los correos quedan deduplicados en la base.

## Railway

El servicio web usa Gunicorn y el puerto que asigna Railway. Configura la migración y el health check en los ajustes del servicio al crearlo.

### Publicar la primera versión

1. En Railway crea un proyecto desde el repositorio `dtapia28/flask`, seleccionando la rama `desarrollo`. Configura el servicio web para desplegar desde la raíz del repositorio. Railway detecta Python y crea el build automáticamente.
2. En el proyecto Railway agrega PostgreSQL. En el servicio web crea `DATABASE_URL` como referencia a la variable `DATABASE_URL` del servicio PostgreSQL; así no se copia ni expone la contraseña de la base.
3. En Variables del servicio web configura `APP_ENV=production`, `SECRET_KEY` y `CRON_SECRET` con valores aleatorios distintos de al menos 32 caracteres, `APP_URL=https://tapiaaraya.com/checklist`, `COOKIE_SECURE=true`, `MAIL_MODE=zeptomail`, `MAIL_FROM` como remitente verificado en ZeptoMail, `ZEPTOMAIL_API_KEY` como Send API key de un Agent, y `ADMIN_EMAIL`. Opcionalmente define `ZEPTOMAIL_API_URL` si tu cuenta utiliza otra región. No uses los valores de ejemplo del `.env`.
4. Añade el dominio que usarán las personas en Settings → Networking y habilita HTTPS. La aplicación admite tanto abrir la raíz del dominio como usar el prefijo `/checklist`; ajusta `APP_URL` a la dirección pública real que usarás. La navegación y los formularios conservan ese prefijo.
5. En Settings del servicio web define **Pre-deploy command** como `flask --app main db upgrade`, **Start command** como `gunicorn --bind 0.0.0.0:$PORT main:app` y **Healthcheck path** como `/health`. Haz el primer deploy. Revisa los logs: un fallo de migración debe detener el release. Cuando el deploy esté activo, abre `/health` y confirma que responde `ok`.
6. En la base ya migrada crea el administrador una sola vez desde Railway → servicio web → Shell con `flask --app main create-admin`. Completa nombre, correo y contraseña en la consola. No uses `seed-demo` en producción.
7. Crea un segundo servicio desde el mismo repositorio y rama. En Settings pon el **Start command** `flask --app main process-closures` y el **Cron schedule** `*/5 * * * *`. Asigna a ese servicio la misma referencia `DATABASE_URL` y las mismas variables `APP_ENV`, `SECRET_KEY`, `APP_URL`, `CRON_SECRET`, `ADMIN_EMAIL`, `MAIL_MODE`, `MAIL_FROM` y `ZEPTOMAIL_API_KEY` (más `ZEPTOMAIL_API_URL` si la definiste). Debe usar la base PostgreSQL del sitio y terminar después de cada ejecución.
8. Entra con el administrador, crea los usuarios familiares, asigna listas y prueba desde un teléfono la invitación, inicio de sesión, marcado de tareas e historial.

Los servicios Cron de Railway usan horario UTC; el código interpreta los cierres según `America/Santiago`. No es necesario mantener un worker encendido: el cron ejecuta el comando y termina. Revisa el costo vigente de Railway y del proveedor SMTP antes de habilitar el proyecto.

Railway está retirando su configuración `railway.json` para servicios nuevos, así que estos pasos usan los ajustes del panel. No se ha creado ni desplegado ningún servicio desde este cambio.

## Pruebas

Ejecuta `python -m pytest -q` para validar permisos, persistencia, cierres de Santiago, deduplicación de correos, rachas de siete días, snapshots históricos, enlaces de un solo uso, autenticación del cron y envíos ZeptoMail simulados. Las pruebas no contactan el proveedor y usan un SQLite temporal aislado; no tocan `instance/checklist.db`.

## Migraciones

Se usa Flask-Migrate/Alembic. Para nueva versión: `flask --app main db migrate -m "descripcion"`, revisar el archivo generado en `migrations/versions/` y aplicar con `flask --app main db upgrade`.

## Alcance actual y notas

Las tareas se congelan en el primer registro diario creado, preservando días cerrados cuando cambien tareas. Usuarios pueden ver y completar sus asignaciones, el servidor aplica el aislamiento y bloquea cambios después del cierre. Administradores gestionan usuarios (activar/desactivar), listas nuevas con tantas secciones de elementos como necesites, asignaciones, pausas y correcciones con motivo; pueden consultar historial de cumplimiento/correos. En esta primera versión las listas son inmutables desde interfaz tras crearse para proteger historial; para cambiar contenido, crea una lista revisada y asígnala. El filtro de cumplimiento permite seleccionar usuario, lista y rango de fechas. Si activas el aviso semanal en una asignación ya creada, su conteo comienza ese día.
