import asyncio
import json
import os
from threading import Lock
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy import text

from database import db


# Векторное хранилище блюд: хранит FAISS-индекс и метаданные,
# умеет строить эмбеддинги и искать похожие блюда по тексту.
class DishVectorStore:
    # Инициализация: сохраняет пути к индексу и метаданным, имя модели,
    # создаёт папку data/ при необходимости и загружает индекс с диска.
    def __init__(
        self,
        index_path: str = "data/dish_index.faiss",
        metadata_path: str = "data/dish_metadata.json",
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ) -> None:
        self.index_path = index_path
        self.metadata_path = metadata_path
        self.model_name = model_name
        self.model: Optional[SentenceTransformer] = None
        self.index: Optional[faiss.Index] = None
        self.metadata: List[Dict] = []
        self.lock = Lock()
        self.vector_size = 384  # for all-MiniLM-L6-v2
        os.makedirs(os.path.dirname(index_path), exist_ok=True)
        self._load_index()

    # Ленивая загрузка модели SentenceTransformer: создаёт её при первом обращении.
    def _load_model(self) -> SentenceTransformer:
        if self.model is None:
            self.model = SentenceTransformer(self.model_name)
        return self.model

    # Загружает FAISS-индекс и метаданные с диска.
    # Если файлов нет — создаёт пустой индекс и пустой список метаданных.
    def _load_index(self) -> None:
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
        else:
            self.index = faiss.IndexFlatIP(self.vector_size)
        if os.path.exists(self.metadata_path):
            with open(self.metadata_path, "r", encoding="utf-8") as f:
                self.metadata = json.load(f)

    # Сохраняет текущий FAISS-индекс и метаданные на диск.
    def _save_index(self) -> None:
        if self.index is None:
            return
        faiss.write_index(self.index, self.index_path)
        with open(self.metadata_path, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)

    # Достаёт из БД доступные блюда вместе с тегами.
    # Если таблиц тегов нет — возвращает блюда с пустым полем tags.
    def _fetch_dishes_with_tags(self) -> List[Dict]:
        with db.engine.connect() as conn:
            if not self._table_exists(conn, "dishes"):
                return []
            tags_exist = self._table_exists(conn, "dish_tag_map") and self._table_exists(
                conn, "dish_tags"
            )
            if tags_exist:
                query = """
                    SELECT d.id, d.name, d.description,
                           COALESCE(GROUP_CONCAT(DISTINCT dt.name), '') AS tags
                    FROM dishes d
                    LEFT JOIN dish_tag_map dtm ON d.id = dtm.dish_id
                    LEFT JOIN dish_tags dt ON dtm.tag_id = dt.id
                    WHERE d.is_available IS NULL OR d.is_available = 1
                    GROUP BY d.id
                    ORDER BY d.id
                """
            else:
                query = """
                    SELECT d.id, d.name, d.description, '' AS tags
                    FROM dishes d
                    WHERE d.is_available IS NULL OR d.is_available = 1
                    ORDER BY d.id
                """
            result = conn.execute(text(query))
            return [dict(row._mapping) for row in result]

    # Проверяет существование таблицы по её имени через SQLAlchemy inspector.
    # При любой ошибке возвращает False.
    @staticmethod
    def _table_exists(conn, table_name: str) -> bool:
        try:
            inspector = db.engine
            from sqlalchemy import inspect
            inspector_obj = inspect(inspector)
            return table_name in inspector_obj.get_table_names()
        except Exception:
            return False

    # Собирает текст для эмбеддинга из названия, описания и тегов блюда.
    def _dish_to_text(self, dish: Dict) -> str:
        parts = [dish.get("name", "")]
        if dish.get("description"):
            parts.append(dish["description"])
        if dish.get("tags"):
            parts.append(f"Теги: {dish['tags']}")
        return " | ".join([p for p in parts if p])

    # Преобразует список текстов в нормализованные float32-векторы
    # с помощью SentenceTransformer.
    def _prepare_vectors(self, texts: List[str]) -> np.ndarray:
        model = self._load_model()
        embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return embeddings.astype("float32")

    # Полностью перестраивает индекс: берёт блюда из БД, считает эмбеддинги,
    # заменяет FAISS-индекс и метаданные, сохраняет на диск.
    def rebuild(self) -> None:
        dishes = self._fetch_dishes_with_tags()
        if not dishes:
            with self.lock:
                self.index = faiss.IndexFlatIP(self.vector_size)
                self.metadata = []
                self._save_index()
            return
        texts = [self._dish_to_text(d) for d in dishes]
        vectors = self._prepare_vectors(texts)
        with self.lock:
            self.index = faiss.IndexFlatIP(self.vector_size)
            self.index.add(vectors)
            self.metadata = dishes
            self._save_index()

    # Асинхронная обёртка над rebuild(): выполняет перестройку в отдельном потоке,
    # чтобы не блокировать event loop.
    async def rebuild_async(self) -> None:
        await asyncio.to_thread(self.rebuild)

    # Ищет top_k ближайших блюд по вектору запроса.
    # Возвращает список словарей с id, name, description, tags и score.
    def search(self, query_vector: np.ndarray, top_k: int = 5) -> List[Dict]:
        with self.lock:
            if self.index is None or self.index.ntotal == 0:
                return []
            top_k = min(top_k, self.index.ntotal)
            distances, indices = self.index.search(query_vector, top_k)
            results = []
            for score_list, idx_list in zip(distances, indices):
                for score, idx in zip(score_list, idx_list):
                    if idx == -1 or idx >= len(self.metadata):
                        continue
                    dish = self.metadata[idx]
                    results.append(
                        {
                            "id": dish["id"],
                            "name": dish["name"],
                            "description": dish.get("description"),
                            "tags": dish.get("tags", ""),
                            "score": float(score),
                        }
                    )
            return results

    # Превращает список тегов в один вектор запроса (теги склеиваются через запятую).
    def embed_tags(self, tags: List[str]) -> np.ndarray:
        text = ", ".join(tags)
        vector = self._prepare_vectors([text])
        return vector

    # Формирует человекочитаемый текст из результатов поиска:
    # название, id, описание, теги и score для каждого блюда.
    def format_context(self, dishes: List[Dict]) -> str:
        lines = []
        for dish in dishes:
            parts = [f"{dish['name']} (id={dish['id']})"]
            if dish.get("description"):
                parts.append(dish["description"])
            if dish.get("tags"):
                parts.append(f"Теги: {dish['tags']}")
            parts.append(f"score={dish['score']:.3f}")
            lines.append(" | ".join(parts))
        return "\n".join(lines)


# Готовый экземпляр хранилища для использования в других модулях.
dish_vector_store = DishVectorStore()


# Фоновая задача: периодически (по умолчанию раз в час) перестраивает индекс.
# Ошибки перестройки игнорируются, чтобы цикл не останавливался.
async def periodic_embeddings_refresh(interval_seconds: int = 3600) -> None:
    while True:
        try:
            await dish_vector_store.rebuild_async()
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)
