from flask import Flask, render_template
import os

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path=""  # Esto hace que los archivos estáticos se sirvan desde la raíz
)

# Configuración para producción
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-secret-key')
app.config['PREFERRED_URL_SCHEME'] = 'https'

@app.get("/")
def home():
    return render_template("index.html")


# ---- Opcional: healthcheck para Railway ----
@app.get("/health")
def health():
    return "ok", 200


if __name__ == "__main__":
    # Configuración para producción
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
