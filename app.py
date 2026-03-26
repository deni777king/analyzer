def get_candidate_domains_llm(domain, our_profile, competitor_type, excluded_domains=None):
    """Генерация URL конкурентов через Groq (без Exa)."""
    excluded = excluded_domains or set()
    site_desc = summarize_profile(our_profile)
    if competitor_type == "direct":
        prompt = f"""Ты ищешь прямых конкурентов для сайта {domain}. Профиль нашего сайта:
{site_desc}

Найди не менее 30 сайтов прямых конкурентов, которые работают в той же нише, с похожим продуктом/услугой, в том же регионе (если регион указан). Исключи маркетплейсы, доски объявлений, государственные учреждения.
Верни только список корневых URL, по одному на строку, без пояснений. Если не знаешь точных URL, укажи реально существующие сайты, которые, по твоему мнению, являются прямыми конкурентами."""
    else:
        prompt = f"""Ты ищешь косвенных конкурентов для сайта {domain}. Профиль нашего сайта:
{site_desc}

Найди не менее 30 сайтов косвенных конкурентов: смежные ниши, альтернативные способы решения той же задачи, пересечение по аудитории. Исключи маркетплейсы, доски объявлений.
Верни только список корневых URL, по одному на строку, без пояснений. Постарайся найти как можно больше реальных сайтов."""
    
    for attempt in range(2):
        try:
            response = call_groq([{"role": "user", "content": prompt}], temperature=0.4, max_tokens=2500)
            urls = extract_candidate_urls(response.get("content", ""))
            filtered = exclude_domains(dedupe_urls(urls), excluded)
            if len(filtered) >= 15:
                return filtered[:40]
            # Если мало, пробуем ещё раз с большей температурой
            if attempt == 0:
                response = call_groq([{"role": "user", "content": prompt}], temperature=0.6, max_tokens=2500)
                urls = extract_candidate_urls(response.get("content", ""))
                filtered = exclude_domains(dedupe_urls(urls), excluded)
                if len(filtered) >= 15:
                    return filtered[:40]
        except Exception as e:
            st.warning(f"Попытка {attempt+1} не удалась: {e}")
    # Возвращаем то, что есть, даже если мало
    return filtered[:30] if filtered else []


def verify_competitors(our_profile, candidate_urls, target_type, our_region=None):
    """Проверка конкурентов с мягкими фильтрами."""
    if our_region is None:
        our_region = extract_region(our_profile)

    verified = []
    rejected = []
    seen = set()
    unique = []
    for raw in candidate_urls:
        url = normalize_root_url(raw)
        dom = get_domain_key(url)
        if dom and dom not in seen:
            seen.add(dom)
            unique.append(url)

    def process(url):
        domain = get_domain_key(url)
        if domain == our_profile.get("domain"):
            return ("reject", {"url": url, "reason": "Свой сайт", "type": target_type})
        if is_blocked_domain(domain):
            return ("reject", {"url": url, "reason": "Маркетплейс/агрегатор", "type": target_type})

        candidate_profile = fetch_site_profile(url)
        if not candidate_profile.get("ok"):
            return ("reject", {"url": url, "reason": f"Недоступен: {candidate_profile.get('issue','ошибка')}", "type": target_type})

        # Мягкая проверка региона – только предупреждение, не отклоняем
        candidate_region = extract_region(candidate_profile)
        region_match = True
        our_wide = our_region.lower() in ["россия","рф","вся россия","по всей стране"]
        cand_wide = candidate_region.lower() in ["россия","рф","вся россия","по всей стране"]
        if not our_wide and not cand_wide and our_region.lower() != candidate_region.lower():
            region_match = False
            # Не отклоняем, просто отмечаем

        # Общие ключевые слова – не обязательны, но влияют на скоринг
        our_keywords_set = set(our_profile.get("keywords", []))
        candidate_keywords_set = set(candidate_profile.get("keywords", []))
        has_common_keywords = bool(our_keywords_set & candidate_keywords_set)

        comparison = compare_profiles(our_profile, candidate_profile)
        score = comparison["score"]

        # Groq проверка релевантности
        groq_ok = is_relevant_competitor_groq(our_profile, candidate_profile)

        # Если Groq сказал "да", зачисляем почти всегда, кроме совсем плохих
        if groq_ok:
            actual_type = classify_competitor(comparison)
            if target_type == "direct":
                # Если сайт явно прямой, или Groq сказал да, зачисляем как прямой
                if actual_type == "direct" or score >= 15:
                    rec = {
                        "url": candidate_profile["final_url"], "domain": candidate_profile["domain"],
                        "title": candidate_profile["title"], "description": candidate_profile["description"],
                        "keywords": candidate_profile.get("keywords",[])[:10], "live": True,
                        "score": score, "relevance": comparison["relevance"],
                        "shared_keywords": comparison["shared_keywords"],
                        "scale_comment": comparison["scale_comment"], "reason": comparison["reason"],
                        "competitor_type": "direct"
                    }
                    return ("verify", rec)
                else:
                    # Косвенный или неподходящий
                    return ("reject", {"url": candidate_profile["final_url"], "reason": f"Groq одобрил, но скоринг низкий ({score})", "type": target_type})
            else:  # indirect
                if actual_type == "indirect" or score >= 10:
                    rec = {
                        "url": candidate_profile["final_url"], "domain": candidate_profile["domain"],
                        "title": candidate_profile["title"], "description": candidate_profile["description"],
                        "keywords": candidate_profile.get("keywords",[])[:10], "live": True,
                        "score": score, "relevance": comparison["relevance"],
                        "shared_keywords": comparison["shared_keywords"],
                        "scale_comment": comparison["scale_comment"], "reason": comparison["reason"],
                        "competitor_type": "indirect"
                    }
                    return ("verify", rec)
                else:
                    return ("reject", {"url": candidate_profile["final_url"], "reason": f"Groq одобрил, но скоринг низкий ({score})", "type": target_type})
        else:
            # Groq сказал нет – отклоняем
            return ("reject", {"url": candidate_profile["final_url"], "reason": "Groq считает нерелевантным", "type": target_type})

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(process, url) for url in unique]
        for fut in concurrent.futures.as_completed(futures):
            try:
                action, data = fut.result()
                (verified if action == "verify" else rejected).append(data)
            except Exception as e:
                rejected.append({"url": "ошибка", "reason": str(e), "type": target_type})
    verified.sort(key=lambda x: x["score"], reverse=True)
    return verified, rejected


def ensure_min_indirect(domain, our_profile, direct_verified, indirect_verified, rejected):
    """Принудительно добираем конкурентов до 15."""
    total_needed = 15
    current_total = len(direct_verified) + len(indirect_verified)
    if current_total >= total_needed:
        return indirect_verified, rejected

    excluded = {our_profile.get("domain", "")}
    excluded.update(item["domain"] for item in direct_verified)
    excluded.update(item["domain"] for item in indirect_verified if item.get("domain"))

    # Сначала пробуем добрать косвенных через LLM
    extra = get_candidate_domains_llm(domain, our_profile, "indirect", excluded)
    extra_ver, extra_rej = verify_competitors(our_profile, extra, "indirect")
    existing = {item["domain"] for item in indirect_verified}
    for item in extra_ver:
        if item["domain"] not in existing:
            indirect_verified.append(item)
            existing.add(item["domain"])
    rejected.extend(extra_rej)

    # Если всё ещё мало, добавляем прямых конкурентов как косвенных
    if len(direct_verified) + len(indirect_verified) < total_needed:
        for item in direct_verified:
            if item["domain"] not in existing:
                indirect_verified.append(item)
                existing.add(item["domain"])
                if len(direct_verified) + len(indirect_verified) >= total_needed:
                    break

    # Если всё равно мало, просто добавляем любые кандидаты из rejected (но только если они были доступны)
    if len(direct_verified) + len(indirect_verified) < total_needed:
        for item in rejected:
            if item.get("url") and "недоступен" not in item["reason"].lower() and "маркетплейс" not in item["reason"].lower():
                # Создаём запись как косвенного конкурента с низким скорингом
                fake_rec = {
                    "url": item["url"], "domain": get_domain_key(item["url"]),
                    "title": "", "description": "", "keywords": [],
                    "live": True, "score": 0, "relevance": "низкая",
                    "shared_keywords": [], "scale_comment": "Добавлен принудительно",
                    "reason": "Недостаточно конкурентов", "competitor_type": "indirect"
                }
                indirect_verified.append(fake_rec)
                if len(direct_verified) + len(indirect_verified) >= total_needed:
                    break

    indirect_verified.sort(key=lambda x: x["score"], reverse=True)
    return indirect_verified, rejected
