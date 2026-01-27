from src.core.stream_manager import StreamManager
from unittest.mock import patch
import sys

def test_streaming_order():
    """優先順位通りに出力されるかテスト"""
    manager = StreamManager(["A", "B"])
    
    # stdoutへの書き込みをキャプチャするリスト
    outputs = []
    
    with patch.object(sys.stdout, 'write', side_effect=outputs.append):
        # 1. Bが先に出力（バッファされるはず）
        manager.write("B", "B-Line1\n")
        assert outputs == [] # まだ出ない
        
        # 2. Aが出力（即出るはず）
        manager.write("A", "A-Line1\n")
        assert outputs == ["A-Line1\n"]
        
        # 3. A終了 -> Bのバッファが出るはず
        manager.finish("A")
        assert "B-Line1\n" in outputs
        
        # 4. Bの続き（即出るはず）
        manager.write("B", "B-Line2\n")
        assert outputs[-1] == "B-Line2\n"

def test_skip_finished_process():
    """Aが終わった時点でBも終わっていた場合、一気にフラッシュしてCへ行くか"""
    manager = StreamManager(["A", "B", "C"])
    outputs = []
    
    with patch.object(sys.stdout, 'write', side_effect=outputs.append):
        manager.write("B", "B-Content\n")
        manager.finish("B") # Bは裏で終了済み
        
        manager.write("A", "A-Content\n")
        manager.finish("A") # A終了 -> ここでBをフラッシュし、B終了検知 -> Cへ
        
        assert "A-Content\n" in outputs
        assert "B-Content\n" in outputs
        
        # 現在のフォーカスはCになっているはず
        manager.write("C", "C-Content\n")
        assert outputs[-1] == "C-Content\n"
