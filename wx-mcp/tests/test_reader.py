"""
单元测试：微信数据库读取器

使用内存 SQLite 数据库模拟解密后的数据库文件，测试 reader 的查询逻辑。
"""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

from wx_mcp.reader import WeChatReader


def _make_contact_db(path: str):
    """创建测试用联系人数据库"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE contact (
            username TEXT,
            nick_name TEXT,
            remark TEXT,
            alias TEXT
        )
    """)
    conn.execute("INSERT INTO contact VALUES ('wxid_test1', '张三', '老板', 'zhangsan')")
    conn.execute("INSERT INTO contact VALUES ('wxid_test2', '李四', '', 'lisi')")
    conn.execute("INSERT INTO contact VALUES ('wxid_test3', '王五', '王总', '')")
    conn.execute("INSERT INTO contact VALUES ('notifymessage', '', '', '')")  # 系统账号
    conn.execute("INSERT INTO contact VALUES ('gh_xxx', '公众号', '', '')")  # 公众号
    conn.commit()
    conn.close()


def _make_session_db(path: str):
    """创建测试用会话数据库"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE SessionTable (
            username TEXT,
            strNickName TEXT,
            summary TEXT,
            last_timestamp INTEGER,
            last_msg_type INTEGER,
            last_sender_display_name TEXT,
            unread_count INTEGER,
            status INTEGER,
            sort_timestamp INTEGER
        )
    """)
    now = int(datetime.now().timestamp() * 1000)
    conn.execute(
        "INSERT INTO SessionTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ('wxid_test1', '张三', '你好', now, 1, '张三', 2, 0, now),
    )
    conn.execute(
        "INSERT INTO SessionTable VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ('wxid_test2', '李四', '收到', now - 10000, 1, '李四', 0, 0, now - 10000),
    )
    conn.commit()
    conn.close()


def _make_message_db(path: str, talker: str = 'wxid_test1'):
    """创建测试用消息数据库"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    import hashlib
    table_hash = hashlib.md5(talker.encode()).hexdigest()
    table_name = f"Msg_{table_hash}"
    conn.execute(f"""
        CREATE TABLE [{table_name}] (
            local_id INTEGER,
            local_type INTEGER,
            create_time INTEGER,
            real_sender_id TEXT,
            message_content BLOB,
            source TEXT
        )
    """)
    now = int(datetime.now().timestamp() * 1000)
    conn.execute(
        f"INSERT INTO [{table_name}] VALUES (1, 1, ?, 'wxid_test1', ?, '')",
        (now, '你好'.encode('utf-8')),
    )
    conn.execute(
        f"INSERT INTO [{table_name}] VALUES (2, 1, ?, 'wxid_test1', ?, '')",
        (now - 1000, '在吗'.encode('utf-8')),
    )
    conn.commit()
    conn.close()


class TestWeChatReaderContacts(unittest.TestCase):
    """联系人读取测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _make_contact_db(os.path.join(self.tmpdir, 'contact', 'contact.db'))
        self.reader = WeChatReader(self.tmpdir)

    def tearDown(self):
        self.reader.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_all_contacts(self):
        """应返回所有非系统联系人"""
        contacts = self.reader.get_contacts()
        self.assertEqual(len(contacts), 3)

    def test_get_contacts_with_keyword(self):
        """关键词搜索应过滤结果"""
        contacts = self.reader.get_contacts(keyword='张三')
        self.assertEqual(len(contacts), 1)
        self.assertEqual(contacts[0]['username'], 'wxid_test1')

    def test_get_contacts_no_system_accounts(self):
        """不应包含系统账号（notifymessage）"""
        contacts = self.reader.get_contacts()
        usernames = [c['username'] for c in contacts]
        self.assertNotIn('notifymessage', usernames)

    def test_get_contacts_no_official_accounts(self):
        """不应包含公众号（gh_xxx）"""
        contacts = self.reader.get_contacts()
        usernames = [c['username'] for c in contacts]
        self.assertNotIn('gh_xxx', usernames)

    def test_get_contacts_display_name_uses_remark(self):
        """display_name 应优先使用 remark"""
        contacts = self.reader.get_contacts()
        test1 = next(c for c in contacts if c['username'] == 'wxid_test1')
        self.assertEqual(test1['display_name'], '老板')

    def test_get_contacts_display_name_fallback(self):
        """无 remark 时 display_name 应使用 nick_name"""
        contacts = self.reader.get_contacts()
        test2 = next(c for c in contacts if c['username'] == 'wxid_test2')
        self.assertEqual(test2['display_name'], '李四')

    def test_search_contacts(self):
        """search_contacts 应返回匹配结果"""
        results = self.reader.search_contacts('李')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['nick_name'], '李四')


class TestWeChatReaderSessions(unittest.TestCase):
    """会话读取测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, 'session'))
        _make_session_db(os.path.join(self.tmpdir, 'session', 'session.db'))
        self.reader = WeChatReader(self.tmpdir)

    def tearDown(self):
        self.reader.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_sessions(self):
        """应返回排序后的会话列表"""
        sessions = self.reader.get_sessions()
        self.assertEqual(len(sessions), 2)
        # 第一条应该是张三（时间更近）
        self.assertEqual(sessions[0]['username'], 'wxid_test1')

    def test_get_sessions_limit(self):
        """limit 参数应控制返回数量"""
        sessions = self.reader.get_sessions(limit=1)
        self.assertEqual(len(sessions), 1)


class TestWeChatReaderMessages(unittest.TestCase):
    """消息读取测试"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, 'message'))
        _make_message_db(os.path.join(self.tmpdir, 'message', 'message_0.db'))
        self.reader = WeChatReader(self.tmpdir)

    def tearDown(self):
        self.reader.close()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_messages(self):
        """应返回聊天消息"""
        msgs = self.reader.get_messages('wxid_test1', limit=10)
        self.assertGreaterEqual(len(msgs), 1)

    def test_get_messages_content_decoded(self):
        """消息内容应被正确解码"""
        msgs = self.reader.get_messages('wxid_test1', limit=10)
        self.assertTrue(any('你好' in m.get('content', '') for m in msgs))

    def test_get_messages_empty_talker(self):
        """空的 talker 应返回空列表"""
        msgs = self.reader.get_messages('', limit=10)
        self.assertEqual(msgs, [])

    def test_get_messages_unknown_talker(self):
        """不存在的 talker 应返回空列表"""
        msgs = self.reader.get_messages('nonexistent_user', limit=10)
        self.assertEqual(msgs, [])


class TestWeChatReaderConnection(unittest.TestCase):
    """连接管理测试"""

    def test_missing_contact_db_raises(self):
        """缺少 contact.db 应抛出异常"""
        tmpdir = tempfile.mkdtemp()
        try:
            reader = WeChatReader(tmpdir)
            with self.assertRaises(FileNotFoundError):
                reader.get_contacts()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_close_release_connections(self):
        """close() 后应能重新获取连接"""
        tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmpdir, 'contact'))
        _make_contact_db(os.path.join(tmpdir, 'contact', 'contact.db'))
        try:
            reader = WeChatReader(tmpdir)
            reader.get_contacts()  # 创建连接
            reader.close()
            reader.get_contacts()  # 重新连接
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestEscapeLike(unittest.TestCase):
    """LIKE 通配符转义测试"""

    def test_plain_text_unchanged(self):
        """普通文本不做转义"""
        result = WeChatReader._escape_like('hello')
        self.assertEqual(result, 'hello')

    def test_percent_escaped(self):
        """% 被转义为 \\%"""
        result = WeChatReader._escape_like('50%')
        self.assertEqual(result, r'50\%')

    def test_underscore_escaped(self):
        """_ 被转义为 \\_"""
        result = WeChatReader._escape_like('a_b')
        self.assertEqual(result, r'a\_b')

    def test_backslash_escaped(self):
        """\\ 本身被双写"""
        result = WeChatReader._escape_like('a\\b')
        self.assertEqual(result, r'a\\b')

    def test_all_wildcards_together(self):
        """混合场景"""
        result = WeChatReader._escape_like(r'100%_test\foo')
        self.assertEqual(result, r'100\%\_test\\foo')


if __name__ == '__main__':
    unittest.main()
