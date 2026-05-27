from __future__ import annotations

import time
from typing import Callable, List

from app.models.metadata_info import MetadataInfo


class GeminiService:
    def generate_metadata(
        self,
        base_title: str,
        short_description: str,
        full_description: str,
        keywords: str,
        target_audience: str,
        category: str,
        tone: str,
        locale_codes: List[str],
        progress_callback: Callable[[object], None] | None = None,
    ) -> List[MetadataInfo]:
        results: List[MetadataInfo] = []
        total = len(locale_codes)

        for index, locale in enumerate(locale_codes, start=1):
            if progress_callback:
                progress_callback(
                    {
                        "message": f"Generating metadata for {locale}",
                        "current": index,
                        "total": total,
                    }
                )
            time.sleep(0.65)
            results.append(
                self._build_metadata(
                    locale=locale,
                    base_title=base_title,
                    short_description=short_description,
                    full_description=full_description,
                    keywords=keywords,
                    target_audience=target_audience,
                    category=category,
                    tone=tone,
                )
            )

        return results

    def _build_metadata(
        self,
        locale: str,
        base_title: str,
        short_description: str,
        full_description: str,
        keywords: str,
        target_audience: str,
        category: str,
        tone: str,
    ) -> MetadataInfo:
        localized_templates = {
            "en": {
                "suffix": "",
                "short": "{short} Built for a smooth Android experience.",
                "full": "{full}\n\nDesigned for {audience} in the {category} category. Highlights: {keywords}. Tone: {tone}.",
            },
            "he": {
                "suffix": "IL",
                "short": "{short} מותאם לחוויית אנדרואיד מהירה וברורה.",
                "full": "{full}\n\nגרסה מקומית לקהל {audience} בקטגוריית {category}. דגשים: {keywords}. טון: {tone}.",
            },
            "fr": {
                "suffix": "FR",
                "short": "{short} Une expérience Android claire et efficace.",
                "full": "{full}\n\nAdapté au public {audience} dans la catégorie {category}. Points clés : {keywords}. Ton : {tone}.",
            },
            "es": {
                "suffix": "ES",
                "short": "{short} Una experiencia Android clara y sencilla.",
                "full": "{full}\n\nAdaptado para {audience} en la categoría {category}. Claves: {keywords}. Tono: {tone}.",
            },
            "de": {
                "suffix": "DE",
                "short": "{short} Eine klare und effiziente Android-Erfahrung.",
                "full": "{full}\n\nLokalisiert fuer {audience} in der Kategorie {category}. Highlights: {keywords}. Ton: {tone}.",
            },
            "pt": {
                "suffix": "BR",
                "short": "{short} Uma experiência Android simples e eficiente.",
                "full": "{full}\n\nAdaptado para {audience} na categoria {category}. Destaques: {keywords}. Tom: {tone}.",
            },
            "zh": {
                "suffix": "CN",
                "short": "{short} 专为清晰流畅的 Android 体验打造。",
                "full": "{full}\n\n面向 {audience}，类别为 {category}。重点：{keywords}。语气：{tone}。",
            },
        }
        language = locale.split("-")[0]
        template = localized_templates.get(language, localized_templates["en"])
        title_suffix = template["suffix"]
        localized_title = base_title if not title_suffix else f"{base_title} {title_suffix}"
        localized_short = template["short"].format(short=short_description)
        localized_full = template["full"].format(
            full=full_description,
            audience=target_audience,
            category=category,
            keywords=keywords,
            tone=tone,
        )

        return MetadataInfo(
            locale=locale,
            app_title=localized_title[:30],
            short_description=localized_short[:80],
            full_description=localized_full[:4000],
            status="Generated",
        )
