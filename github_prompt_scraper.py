import requests
from bs4 import BeautifulSoup
import re
import time
from datetime import datetime
import urllib.parse
import json
from openai import OpenAI
import mysql.connector
from mysql.connector import Error

class GithubPromptScraper:
    def __init__(self):
        self.base_url = "https://github.com/linexjlin/GPTs/blob/main/prompts"
        self.raw_content_base = "https://raw.githubusercontent.com/linexjlin/GPTs/main/prompts/"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # DeepSeek API设置
        self.client = OpenAI(
            api_key="sk-de9f0402e48e4e24b4653721ee03724d",
            base_url="https://api.deepseek.com/v1"
        )

        # 添加数据库配置
        self.db_config = {
            'host': 'localhost',
            'user': 'promptadmin',
            'password': 'admin',  # 填写你的数据库密码
            'database': 'PromptEverything'  # 你的数据库名称
        }

    def connect_to_database(self):
        try:
            connection = mysql.connector.connect(**self.db_config)
            if connection.is_connected():
                print("Successfully connected to the database")
                return connection
        except Error as e:
            print(f"Error connecting to MySQL database: {e}")
            return None

    def insert_prompt(self, cursor, title, content):
        try:
            sql = """INSERT INTO PromptInfo (title, content, created_at, user_id, is_public)
                     VALUES (%s, %s, %s, %s, %s)"""
            values = (title, content, datetime.now(), 1, True)
            cursor.execute(sql, values)
            return cursor.lastrowid
        except Error as e:
            print(f"Error inserting prompt: {e}")
            return None

    def insert_tag(self, cursor, tag_name):
        try:
            # 检查标签是否已存在
            cursor.execute("SELECT id FROM Tags WHERE name = %s", (tag_name,))
            result = cursor.fetchone()
            if result:
                return result[0]
            
            # 插入新标签
            sql = """INSERT INTO Tags (name, created_at)
                     VALUES (%s, %s)"""
            values = (tag_name, datetime.now())
            cursor.execute(sql, values)
            return cursor.lastrowid
        except Error as e:
            print(f"Error inserting tag: {e}")
            return None

    def insert_prompt_tag(self, cursor, prompt_id, tag_id):
        try:
            sql = """INSERT INTO PromptTag (prompt_id, tag_id, created_at)
                     VALUES (%s, %s, %s)"""
            values = (prompt_id, tag_id, datetime.now())
            cursor.execute(sql, values)
        except Error as e:
            print(f"Error inserting prompt-tag relation: {e}")

    def get_md_files(self):
        try:
            response = requests.get("https://api.github.com/repos/linexjlin/GPTs/git/trees/main?recursive=1", headers=self.headers)
            response.raise_for_status()
            data = response.json()
            
            files = []
            for item in data['tree']:
                if item['path'].startswith('prompts/') and item['path'].endswith('.md'):
                    file_name = item['path'].split('/')[-1]
                    files.append({
                        "name": file_name,
                        "download_url": self.raw_content_base + urllib.parse.quote(file_name)
                    })
            
            print(f"Found {len(files)} markdown files")
            return files
            
        except requests.exceptions.RequestException as e:
            print(f"Error fetching files: {e}")
            if 'response' in locals():
                print(f"Response content: {response.text}")
            return []

    def get_file_content(self, file_url):
        try:
            response = requests.get(file_url, headers=self.headers)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"Error fetching file content: {e}")
            print(f"URL: {file_url}")
            time.sleep(2)
            return None

    def extract_tags_with_deepseek(self, title, content):
        try:
            prompt = f"""Analyze the following prompt title and content, generate up to 4 relevant tags in English.
Title: {title}
Content Preview: {content[:500]}...

Requirements for tags:
1. Must be single English words
2. Must be relevant to the prompt's purpose or domain
3. Should be common technical or professional terms
4. No compound words or phrases
5. No abbreviations except common ones (AI, ML, NLP)

Examples of good tags:
- Writing, Coding, Marketing, Analysis
- Research, Teaching, Learning, Design
- Business, Finance, Medical, Legal

Examples of bad tags:
- AIAssistant (compound word)
- GPT (excluded term)
- MachineLearning (should be separate)
- Prompt (excluded term)

Return only the tags, separated by commas (max 4 tags)."""

            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a professional English tag classifier. Generate only standard English tags."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=50,
                stream=False
            )

            # 解析响应并清理标签
            tags = response.choices[0].message.content.strip().split(',')
            tags = [tag.strip() for tag in tags]
            
            # 过滤和清理标签
            filtered_tags = []
            excluded_tags = {'gpt', 'prompt', 'ai', 'assistant', '', 'bot', 'chatbot'}
            
            for tag in tags:
                tag = tag.lower().strip()
                # 只保留字母和常见缩写
                if (
                    tag and 
                    tag not in excluded_tags and 
                    len(tag) > 1 and 
                    (tag.isalpha() or tag in {'nlp', 'ml', 'ui', 'ux'})
                ):
                    filtered_tags.append(tag.capitalize())  # 首字母大写
            
            # 确保最多4个标签
            filtered_tags = filtered_tags[:4]
            
            if not filtered_tags:  # 如果没有有效标签
                return ['Assistant']
                
            return filtered_tags

        except Exception as e:
            print(f"Error in DeepSeek tag extraction: {e}")
            return ['Assistant']  # 默认标签

    def translate_to_english(self, text):
        try:
            prompt = f"""Translate the following text to English. Keep any code blocks, URLs, or technical terms unchanged.
If the text is already in English, return it as is.

Text to translate:
{text}

Return only the translated text, no explanations."""

            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a professional translator. Translate text to English while preserving technical terms and formatting."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000,
                stream=False
            )

            translated_text = response.choices[0].message.content.strip()
            return translated_text
        except Exception as e:
            print(f"Error in translation: {e}")
            return text  # 如果翻译失败，返回原文

    def is_english(self, text):
        # 检查文本是否主要为英文
        # 忽略代码块、URL和特殊字符
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)  # 移除代码块
        text = re.sub(r'http\S+|www.\S+', '', text)  # 移除URL
        text = re.sub(r'[^a-zA-Z\s]', '', text)  # 只保留英文字母和空格
        
        if not text.strip():  # 如果处理后文本为空
            return True
            
        # 计算英文字符占比
        english_chars = len(re.findall(r'[a-zA-Z]', text))
        total_chars = len(text.strip())
        return english_chars / total_chars > 0.8 if total_chars > 0 else True

    def process_files_to_database(self):
        connection = self.connect_to_database()
        if not connection:
            return
        
        cursor = connection.cursor()
        md_files = self.get_md_files()
        
        try:
            for file in md_files:
                print(f"Processing: {file['name']}")
                content = self.get_file_content(file["download_url"])
                
                if content:
                    # 插入prompt
                    title = file["name"].replace(".md", "")
                    prompt_id = self.insert_prompt(cursor, title, content)
                    
                    if prompt_id:
                        # 获取并插入标签
                        tags = self.extract_tags_with_deepseek(title, content)
                        print(f"Generated tags: {tags}")
                        
                        for tag in tags:
                            tag_id = self.insert_tag(cursor, tag)
                            if tag_id:
                                self.insert_prompt_tag(cursor, prompt_id, tag_id)
                
                time.sleep(0.5)
            
            connection.commit()
            print("All data has been successfully inserted into the database")
            
        except Error as e:
            print(f"Database error: {e}")
            connection.rollback()
        finally:
            cursor.close()
            connection.close()

if __name__ == "__main__":
    scraper = GithubPromptScraper()
    scraper.process_files_to_database()