from flask import Flask, render_template, send_from_directory
app = Flask(__name__)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/create')
def create():
    return render_template('create.html')

@app.route('/vote')
def vote():
    return render_template('vote.html')

@app.route('/result')
def result():
    return render_template('result.html')

# allow serving static files when running with flask run (flask does this automatically, kept for clarity)
@app.route('/static/<path:path>')
def static_dir(path):
    return send_from_directory('static', path)

if __name__ == '__main__':
    app.run(debug=True)