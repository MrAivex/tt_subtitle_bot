import asyncio
import time
from typing import Optional

class ProgressTracker:
    """Отслеживает прогресс обработки видео и обновляет сообщение."""
    
    def __init__(self, bot, chat_id: int, status_id: int, total_duration_sec: float = 0):
        self.bot = bot
        self.chat_id = chat_id
        self.status_id = status_id
        self.total_duration = total_duration_sec
        self.current_stage = ""
        self.stage_progress = 0.0  # 0.0 to 1.0
        self.start_time = time.time()
        self.last_update_time = 0
        self.update_interval = 3  # секунд между обновлениями
        self.is_active = True
        
    def _format_time(self, seconds: float) -> str:
        """Форматирует секунды в читаемый вид."""
        if seconds < 60:
            return f"{int(seconds)} сек"
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d} мин"
    
    def _estimate_remaining(self, stage_progress: float, stage_duration_estimate: float) -> float:
        """Оценивает оставшееся время на этапе."""
        if stage_progress <= 0:
            return stage_duration_estimate
        elapsed = time.time() - self.start_time
        if stage_progress >= 1.0:
            return 0
        return (elapsed / stage_progress) * (1 - stage_progress)
    
    async def update(self, stage: str, progress: float = 0.0, 
                     stage_estimate_sec: float = 0, force: bool = False):
        """Обновляет статус. progress: 0.0-1.0 для текущего этапа."""
        if not self.is_active or not self.status_id:
            return
            
        now = time.time()
        if not force and (now - self.last_update_time) < self.update_interval:
            return
        
        self.current_stage = stage
        self.stage_progress = progress
        self.last_update_time = now
        
        # Считаем общее время
        elapsed = time.time() - self.start_time
        
        # Формируем прогресс-бар для скачивания (единственный этап с точным %)
        progress_bar = ""
        if stage == "download" and progress > 0:
            filled = int(progress * 10)
            empty = 10 - filled
            progress_bar = f" [{filled * '█'}{empty * '░'}] {int(progress * 100)}%"
        
        # Оцениваем оставшееся время
        remaining = ""
        if stage_estimate_sec > 0 and progress > 0:
            est_remaining = self._estimate_remaining(progress, stage_estimate_sec)
            remaining = f" (~{self._format_time(est_remaining)} осталось)"
        
        # Формируем текст
        lines = [
            f"🎬 *Обработка видео*{progress_bar}",
            "",
            f"⏱ Прошло: {self._format_time(elapsed)}",
            "",
            f"📍 {stage}",
        ]
        
        if remaining:
            lines.append(f"⏳{remaining}")
        
        text = "\n".join(lines)
        
        try:
            await self.bot.edit_message(self.chat_id, self.status_id, text)
        except Exception as e:
            # Если edit_message упал (например, сообщение не изменилось), игнорируем
            if "message is not modified" not in str(e).lower():
                print(f"[ProgressTracker] Edit error: {e}")
    
    async def finish(self, success: bool = True):
        """Завершает трекинг."""
        self.is_active = False
        elapsed = time.time() - self.start_time
        
        if success:
            text = f"✅ Готово! Обработка заняла {self._format_time(elapsed)}"
        else:
            text = f"❌ Ошибка после {self._format_time(elapsed)}"
        
        try:
            await self.bot.edit_message(self.chat_id, self.status_id, text)
        except:
            pass
    
    async def stage_complete(self, stage: str):
        """Отмечает этап как завершённый."""
        await self.update(stage, progress=1.0, force=True)