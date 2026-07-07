"""
从解密后的微信数据库中读取消息、联系人、会话

WeChat 4.x 使用 WCDB，每个会话的消息存储在独立的 Msg_<md5(talker)> 表中。
"""
import os, sqlite3, hashlib, logging
from typing import List, Dict, Optional
from datetime import datetime

import zstandard as zstd

log = logging.getLogger('wx-mcp.reader')


def _decompress(content: bytes) -> str:
    """解压消息内容（ZSTD 压缩）"""
    if not content:
        return ""
    if content[:4] == b'\x28\xb5\x2f\xfd':
        try:
            return zstd.decompress(content).decode('utf-8', errors='replace')
        except Exception as e:
            log.warning(f"ZSTD 解压失败 ({len(content)} bytes): {e}")
    try:
        return content.decode('utf-8', errors='replace')
    except Exception as e:
        log.warning(f"字节解码失败 ({len(content)} bytes): {e}")
        return str(content)


class WeChatReader:
    """微信数据库读取器"""

    def __init__(self, decrypted_dir: str):
        self.decrypted_dir = decrypted_dir

    def _get_db(self, rel_path: str) -> sqlite3.Connection:
        """打开解密后的数据库"""
        path = os.path.join(self.decrypted_dir, rel_path)
        if not os.path.exists(path):
            raise FileNotFoundError(f"数据库不存在: {path}")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_contacts(self, keyword: str = "", limit: int = 50) -> List[Dict]:
        """获取联系人列表"""
        conn = self._get_db('contact/contact.db')
        try:
            sql = """
                SELECT username, nick_name, remark, alias,
                       CASE
                           WHEN remark IS NOT NULL AND remark != '' THEN remark
                           WHEN nick_name IS NOT NULL AND nick_name != '' THEN nick_name
                           ELSE username
                       END as display_name
                FROM contact
                WHERE username IS NOT NULL AND username NOT LIKE 'gh_%' AND username NOT IN (
                    'notifymessage', 'fmessage', 'medianote', 'floatbottle'
                )
            """
            params = []
            if keyword:
                sql += " AND (nick_name LIKE ? OR remark LIKE ? OR alias LIKE ?)"
                like = f"%{keyword}%"
                params = [like, like, like]
            sql += " ORDER BY display_name LIMIT ?"
            params.append(limit)

            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log.error(f"get_contacts 查询失败: {e}", exc_info=True)
            raise
        finally:
            conn.close()

    def get_sessions(self, limit: int = 20) -> List[Dict]:
        """获取最近会话列表"""
        conn = self._get_db('session/session.db')
        try:
            rows = conn.execute("""
                SELECT username, summary, last_timestamp, last_msg_type,
                       last_sender_display_name, unread_count, status
                FROM SessionTable
                ORDER BY sort_timestamp DESC LIMIT ?
            """, (limit,)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if d.get('last_timestamp'):
                    ts = d['last_timestamp']
                    if ts > 1e15:
                        ts = ts / 1000000
                    elif ts > 1e12:
                        ts = ts / 1000
                    d['time'] = datetime.fromtimestamp(ts).isoformat()
                result.append(d)
            return result
        except Exception as e:
            log.error(f"get_sessions 查询失败: {e}", exc_info=True)
            raise
        finally:
            conn.close()

    def _get_msg_table(self, conn: sqlite3.Connection, talker: str) -> Optional[str]:
        """根据 talker 查找对应的 Msg_<md5> 表"""
        try:
            table_hash = hashlib.md5(talker.encode()).hexdigest()
            table_name = f"Msg_{table_hash}"
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE name=?", (table_name,)
            ).fetchone()
            return table_name if exists else None
        except Exception as e:
            log.error(f"_get_msg_table(talker={talker}) 失败: {e}")
            return None

    def get_messages(self, talker: str, limit: int = 50, offset: int = 0) -> List[Dict]:
        """获取与某联系人的聊天记录"""
        talker = talker.strip()
        if not talker:
            return []

        all_msgs = []
        for db_name in ['message/message_0.db', 'message/message_1.db']:
            try:
                conn = self._get_db(db_name)
            except FileNotFoundError as e:
                log.warning(f"get_messages: {e}")
                continue
            except Exception as e:
                log.error(f"打开数据库 {db_name} 失败: {e}", exc_info=True)
                continue

            try:
                table = self._get_msg_table(conn, talker)
                if not table:
                    conn.close()
                    continue

                rows = conn.execute(f"""
                    SELECT local_id, local_type, create_time, real_sender_id,
                           message_content, source
                    FROM [{table}]
                    WHERE message_content IS NOT NULL
                    ORDER BY create_time DESC
                    LIMIT ? OFFSET ?
                """, (limit, offset)).fetchall()

                for r in rows:
                    d = dict(r)
                    content = d.get('message_content') or b''
                    d['content'] = _decompress(content)
                    d['type'] = d.get('local_type', 0)
                    if d.get('create_time'):
                        ts = d['create_time']
                        if ts > 1e15:
                            ts = ts / 1000000
                        elif ts > 1e12:
                            ts = ts / 1000
                        d['time'] = datetime.fromtimestamp(ts).isoformat()
                    all_msgs.append(d)

            except Exception as e:
                log.error(f"读取 {db_name}/{talker} 消息失败: {e}", exc_info=True)
            finally:
                conn.close()

        all_msgs.sort(key=lambda x: x.get('create_time', 0), reverse=True)
        return all_msgs[:limit]

    def search_contacts(self, keyword: str) -> List[Dict]:
        """搜索联系人"""
        return self.get_contacts(keyword=keyword, limit=20)
