# ЭФБО-08-24, СЫСОЕВ ВИТАЛИЙ ВЯЧЕСЛАВОВИЧ
# 1. КЛОНИРОВАНИЕ И УСТАНОВКА:
Создайте папку проекта и скопируйте все файлы
cd fastapi_auth_project

Создайте виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac или venv\Scripts\activate  # Windows

Установите зависимости
pip install -r requirements.txt

# 2. НАСТРОЙКА PSQL(решил выбрать psql, а не sqlite):
Запустите PostgreSQL
sudo service postgresql start  # Linux 

Создайте базу данных
sudo -u postgres psql
CREATE DATABASE fastapi_auth;
\q

# 3. НАЙСТРОЙКА ОКРУЖЕНИЯ
cp .env.example .env
#отредактируйте .env под свои параметры БД

# 4. ИНИЦИАЛИЗАЦИЯ БД И ЗАПУСК ПРОЕКТА:
   python init_db.py
   uvicorn main:app --reload


# ТЕСТИРОВАНИЕ ЭНДПОИНТОВ:
#Регистрация
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "alice123", "role": "user"}'

#Логин (сохраните токен)
TOKEN=$(curl -s -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "alice123"}' | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")


# TODO CRUD операции:
#Создать Todo
curl -X POST http://localhost:8000/todos/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Buy milk", "description": "From the store"}'

#Получить все Todo
curl -X GET "http://localhost:8000/todos/" \
  -H "Authorization: Bearer $TOKEN"

#Получить Todo по ID
curl -X GET http://localhost:8000/todos/1 \
  -H "Authorization: Bearer $TOKEN"

#Обновить Todo
curl -X PUT http://localhost:8000/todos/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"completed": true}'

#Удалить Todo
curl -X DELETE http://localhost:8000/todos/1 \
  -H "Authorization: Bearer $TOKEN"

# Защищенные эндпоинты
#Базовый защищенный ресурс
curl -X GET http://localhost:8000/protected_resource \
  -H "Authorization: Bearer $TOKEN"

#Список пользователей (только admin)
curl -X GET http://localhost:8000/admin/users \
  -H "Authorization: Bearer $TOKEN"

#Выход
curl -X POST http://localhost:8000/logout \
  -H "Authorization: Bearer $TOKEN"

#DEV режим:
http://localhost:8000/docs
login: admin
password: docs123
