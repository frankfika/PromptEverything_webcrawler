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
import openai

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
        description = self.generate_description(content)
        cursor.execute('''
            INSERT INTO PromptInfo (title, content, description, copied_times, is_public)
            VALUES (%s, %s, %s, %s, %s)
        ''', (title, content, description, 1, True))
        return cursor.lastrowid

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

    def generate_tags(self, title, content):
        """
        分析内容并生成相关标签
        返回最多4个标签
        """
        try:
            prompt = f"""Analyze the following prompt content and generate relevant tags.

Content to analyze:
Title: {title}
Content: {content[:500]}...

Requirements:
1. Generate exactly 4 tags
2. Each tag must be a single English word
3. Tags should reflect the content's domain and purpose
4. Avoid general terms like 'AI', 'GPT', 'prompt', 'assistant'
5. Focus on professional/technical terms

Return only the tags, separated by commas."""

            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a professional content tagger. Generate precise and relevant tags."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=50,
                stream=False
            )

            tags = response.choices[0].message.content.strip().split(',')
            tags = [tag.strip().lower() for tag in tags]
            
            # 过滤无效标签
            excluded_tags = {'gpt', 'prompt', 'ai', 'assistant', 'bot', 'chatbot'}
            filtered_tags = [
                tag.capitalize() 
                for tag in tags 
                if tag and tag not in excluded_tags and len(tag) > 1 and (tag.isalpha() or tag in {'nlp', 'ml', 'ui', 'ux'})
            ]
            
            return filtered_tags[:4] if filtered_tags else ['Assistant']

        except Exception as e:
            print(f"Error in tag generation: {e}")
            return ['Assistant']

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
                    # 插入 PromptInfo
                    title = file["name"].replace(".md", "")
                    prompt_id = self.insert_prompt(cursor, title, content)
                    
                    if prompt_id:
                        # 生成并插入标签
                        tags = self.generate_tags(title, content)
                        print(f"Generated tags for {title}: {tags}")
                        
                        for tag in tags:
                            # 插入或获取已存在的标签ID
                            tag_id = self.insert_tag(cursor, tag)
                            if tag_id:
                                # 创建 PromptInfo 和 Tags 的关联
                                self.insert_prompt_tag(cursor, prompt_id, tag_id)
                                print(f"Added tag '{tag}' to prompt '{title}'")
                
                time.sleep(0.5)
            
            connection.commit()
            print("All data has been successfully inserted into the database")
            
        except Error as e:
            print(f"Database error: {e}")
            connection.rollback()
        finally:
            cursor.close()
            connection.close()

    def generate_description(self, content):
        """
        使用DeepSeek API根据prompt内容生成简短描述
        返回200字以内的总结
        """
        try:
            prompt = f"""Analyze the following prompt content and generate a concise description.

Content to analyze:
{content[:1000]}...

Requirements:
1. Maximum 200 characters in Chinese
2. Focus on the main purpose and key features
3. Describe what this prompt can do
4. Be specific and practical

Return the description directly, no additional text or explanation."""

            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "You are a professional content analyzer. Generate concise descriptions in Chinese."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=150,
                stream=False
            )

            description = response.choices[0].message.content.strip()
            # 确保描述不超过200字
            return description[:200]

        except Exception as e:
            print(f"Error in description generation: {e}")
            return ""

if __name__ == "__main__":
    scraper = GithubPromptScraper()
    scraper.process_files_to_database()