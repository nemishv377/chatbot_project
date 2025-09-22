# chatbot_project

## System Requirements

- Python v3.11.x
- Virtualenv v20.27.x
- SQLite (default DB, no additional installation needed)
- Django v5.1.x
- Groq API key

---

## Project Setup Instructions

### Clone the Project
1. **Clone the repository**:
    ```sh
    git clone https://github.com/nemishv377/chatbot_project.git
    ```
2. **Navigate to the project directory**:
    ```sh
    cd chatbot_project
    ```

---

## Without Docker

### Create a Virtual Environment
1. **Create the virtual environment**:
    ```sh
    python3 -m venv env
    ```
2. **Activate the virtual environment**:
    - On Linux/macOS:
        ```sh
        source env/bin/activate
        ```
    - On Windows:
        ```sh
        .\env\Scripts\activate
        ```

3. **Install the dependencies:**
    - Install dependencies from `requirements.txt`:
        ```sh
        pip install -r requirements.txt
        ```

4. **Set up environment variables:**
    - Copy the `.env.example` file to `.env`:
        ```sh
        cp .env.example .env
        ```

5. **Database Migrations:**
    - Apply migrations:
        ```sh
        python manage.py migrate
        ```

6. **Run the development server:**
    - Start the server:
        ```sh
        python manage.py runserver
        ```
    - Access the application at:
        ```
        http://localhost:8000
        ```
