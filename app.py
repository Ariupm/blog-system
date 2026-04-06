from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO
from PIL import Image
import base64
import os
from pathlib import Path
import sys

if getattr(sys, 'frozen', False):
    # 如果是打包后的可执行文件
    template_folder = os.path.join(sys._MEIPASS, 'templates')
    app = Flask(__name__, template_folder=template_folder)
else:
    # 如果是开发环境
    app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
# 使用 SQLite 数据库（适合免费部署）
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{os.path.join(basedir, "blog.db")}')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# 数据库模型
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    articles = db.relationship('Article', backref='author', lazy=True)


class Article(db.Model):
    __tablename__ = 'articles'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_public = db.Column(db.Boolean, default=False)
    font_size = db.Column(db.String(20), default='medium')
    font_color = db.Column(db.String(20), default='#000000')
    created_at = db.Column(db.TIMESTAMP, server_default=db.func.current_timestamp())
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    images = db.relationship('ArticleImage', backref='article', lazy=True)


class ArticleImage(db.Model):
    __tablename__ = 'images'
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('articles.id'), nullable=False)
    image_data = db.Column(db.LargeBinary, nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 路由
@app.route('/')
def index():
    public_articles = Article.query.filter_by(is_public=True).order_by(Article.created_at.desc()).all()
    return render_template('index.html', articles=public_articles)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash('用户名已存在')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('邮箱已存在')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash('注册成功，请登录')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    user_articles = Article.query.filter_by(user_id=current_user.id).order_by(Article.created_at.desc()).all()
    return render_template('dashboard.html', articles=user_articles)


@app.route('/create_article', methods=['GET', 'POST'])
@login_required
def create_article():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        is_public = 'is_public' in request.form
        font_size = request.form['font_size']
        font_color = request.form['font_color']

        new_article = Article(
            title=title,
            content=content,
            is_public=is_public,
            font_size=font_size,
            font_color=font_color,
            user_id=current_user.id
        )

        db.session.add(new_article)
        db.session.commit()

        # 处理图片上传
        if 'images' in request.files:
            images = request.files.getlist('images')
            for image in images:
                if image.filename:
                    # 调整图片大小以节省空间
                    img = Image.open(image.stream)
                    img.thumbnail((800, 800))
                    img_byte_arr = BytesIO()
                    img.save(img_byte_arr, format=img.format if img.format else 'JPEG')
                    img_byte_arr = img_byte_arr.getvalue()

                    new_image = ArticleImage(
                        article_id=new_article.id,
                        image_data=img_byte_arr
                    )
                    db.session.add(new_image)

        db.session.commit()
        flash('文章创建成功')
        return redirect(url_for('dashboard'))

    return render_template('create_article.html')


@app.route('/article/<int:article_id>')
def view_article(article_id):
    article = Article.query.get_or_404(article_id)
    if not article.is_public and (not current_user.is_authenticated or current_user.id != article.user_id):
        flash('无权查看此文章')
        return redirect(url_for('index'))

    # 获取文章中的图片
    images = []
    for img in article.images:
        img_data = base64.b64encode(img.image_data).decode('utf-8')
        images.append(f"data:image/jpeg;base64,{img_data}")

    return render_template('article.html', article=article, images=images)


@app.route('/edit_article/<int:article_id>', methods=['GET', 'POST'])
@login_required
def edit_article(article_id):
    article = Article.query.get_or_404(article_id)
    if article.user_id != current_user.id:
        flash('无权编辑此文章')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        article.title = request.form['title']
        article.content = request.form['content']
        article.is_public = 'is_public' in request.form
        article.font_size = request.form['font_size']
        article.font_color = request.form['font_color']

        # 处理图片上传
        if 'images' in request.files:
            images = request.files.getlist('images')
            for image in images:
                if image.filename:
                    # 调整图片大小以节省空间
                    img = Image.open(image.stream)
                    img.thumbnail((800, 800))
                    img_byte_arr = BytesIO()
                    img.save(img_byte_arr, format=img.format if img.format else 'JPEG')
                    img_byte_arr = img_byte_arr.getvalue()

                    new_image = ArticleImage(
                        article_id=article.id,
                        image_data=img_byte_arr
                    )
                    db.session.add(new_image)

        db.session.commit()
        flash('文章更新成功')
        return redirect(url_for('dashboard'))

    # 获取文章中的图片
    images = []
    for img in article.images:
        img_data = base64.b64encode(img.image_data).decode('utf-8')
        images.append(f"data:image/jpeg;base64,{img_data}")

    return render_template('edit_article.html', article=article, images=images)


@app.route('/delete_article/<int:article_id>')
@login_required
def delete_article(article_id):
    article = Article.query.get_or_404(article_id)
    if article.user_id != current_user.id:
        flash('无权删除此文章')
        return redirect(url_for('dashboard'))

    db.session.delete(article)
    db.session.commit()
    flash('文章已删除')
    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # 生产环境使用环境变量指定的端口
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)