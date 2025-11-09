from flask import Flask, render_template

# Si tus carpetas se llaman exactamente "templates" y "static",
# no hace falta pasar los parámetros, pero los dejo explícitos.
app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
)

# Puedes verificar la versión en logs si quieres
# import flask; print("Flask version:", flask.__version__)

@app.get("/")
def home():
    return render_template("index.html")


# ---- Opcional: healthcheck para Railway ----
@app.get("/health")
def health():
    return "ok", 200


if __name__ == "__main__":
    # Para correr local
    app.run(host="0.0.0.0", port=3000, debug=True)
