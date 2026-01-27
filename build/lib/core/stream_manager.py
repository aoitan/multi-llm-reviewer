import sys
import threading
from collections import deque

class StreamBuffer:
    def __init__(self, name):
        self.name = name
        self.buffer = deque()
        self.is_finished = False
        self.output_collected = [] # 最終的な全出力を保持

class StreamManager:
    def __init__(self, priority_order):
        """
        Args:
            priority_order (list): プロセス名のリスト（優先順位順）
        """
        self.priority_queue = list(priority_order)
        self.buffers = {name: StreamBuffer(name) for name in priority_order}
        self.current_focus_index = 0
        self.lock = threading.Lock()
        
    def get_current_focus(self):
        if self.current_focus_index < len(self.priority_queue):
            return self.priority_queue[self.current_focus_index]
        return None

    def write(self, source, text):
        """プロセスからの出力を受け取る"""
        with self.lock:
            # 全出力の保存
            if source in self.buffers:
                self.buffers[source].output_collected.append(text)

            current = self.get_current_focus()
            
            if source == current:
                # 現在のフォーカス対象なら即出力
                sys.stdout.write(text)
                sys.stdout.flush()
            elif source in self.buffers:
                # それ以外はバッファリング
                self.buffers[source].buffer.append(text)

    def finish(self, source):
        """プロセス終了通知"""
        with self.lock:
            if source in self.buffers:
                self.buffers[source].is_finished = True
                
            # フォーカス対象が終了した場合、次へ切り替え
            if source == self.get_current_focus():
                self._switch_to_next()

    def _switch_to_next(self):
        """次の優先度のプロセスにフォーカスを移し、バッファを吐き出す"""
        while True:
            self.current_focus_index += 1
            next_focus = self.get_current_focus()
            
            if not next_focus:
                break # 全て完了
            
            # 次のターゲットのバッファを一気に出力
            buf_obj = self.buffers[next_focus]
            while buf_obj.buffer:
                sys.stdout.write(buf_obj.buffer.popleft())
            sys.stdout.flush()
            
            # もし次のターゲットも既に終了していたら、さらに次へ
            if not buf_obj.is_finished:
                break

    def get_full_output(self, source):
        """指定されたソースの全出力を取得する"""
        if source in self.buffers:
            return "".join(self.buffers[source].output_collected)
        return ""
