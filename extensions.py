# 扩展：SQLAlchemy 实例，供 models 与 routes 使用，避免循环导入
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
