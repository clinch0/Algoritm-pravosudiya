# -*- coding: utf-8 -*-
"""Тесты анонимизатора персональных данных (app/anonymizer.py)."""
from app.anonymizer import anonymization_report, mask_text


def test_mask_full_name_mid_sentence():
    # ФИО в середине предложения заменяется токеном <ФИО>
    text = "Осуждённый Иванов Петр Сергеевич признан виновным."
    masked = mask_text(text)
    assert "<ФИО>" in masked
    assert "Иванов" not in masked
    assert "Петр" not in masked
    assert "Сергеевич" not in masked


def test_mask_dates_phone_email():
    # даты (цифрами и прописью), телефон и email
    text = ("Преступление совершено 12.03.1990, а также 5 марта 1990 года. "
            "Телефон +7 (900) 123-45-67, почта ivanov@example.ru.")
    masked = mask_text(text)
    assert "<ДАТА>" in masked
    assert "<ТЕЛЕФОН>" in masked
    assert "<EMAIL>" in masked
    assert "12.03.1990" not in masked
    assert "марта" not in masked
    assert "123-45-67" not in masked
    assert "ivanov@example.ru" not in masked


def test_legal_terms_not_masked():
    # юридическая терминология не должна маскироваться
    text = ("Согласно постановлению Пленума Верховного Суда Российской Федерации "
            "при назначении наказания по ч. 2 ст. 158 УК РФ суд учитывает "
            "положения Общей части Уголовного кодекса.")
    masked = mask_text(text)
    for term in ["Пленума", "Верховного", "Суда", "Российской", "Федерации",
                 "УК РФ", "Общей части", "Уголовного кодекса", "158"]:
        assert term in masked, f"термин замаскирован: {term}"
    assert "<ФИО>" not in masked


def test_mask_documents_inn_snils_address():
    # паспорт, ИНН, СНИЛС и полный адрес
    text = ("Паспорт серия 1234 номер 567890, ИНН 7701234567, СНИЛС 123-456-789 01. "
            "Проживает по адресу: г. Москва, ул. Ленина, д. 1, кв. 2.")
    masked = mask_text(text)
    assert "<ПАСПОРТ>" in masked
    assert "<ИНН>" in masked
    assert "<СНИЛС>" in masked
    assert "<АДРЕС>" in masked
    assert "1234" not in masked
    assert "7701234567" not in masked
    assert "123-456-789 01" not in masked
    assert "ул. Ленина" not in masked


def test_anonymization_report_counts():
    # счётчики замен по типам (для журнала аудита)
    text = ("Осуждённый Иванов и осуждённый Петров совершили кражу "
            "12.03.2024 и 5 марта 2024 года.")
    report = anonymization_report(text)
    assert report["ФИО"] == 2
    assert report["ДАТА"] == 2
    assert report["total"] == 4
    assert report["ТЕЛЕФОН"] == 0


def test_citizen_placeholder_kept():
    # псевдоним «гражданин А.» — уже обезличенные данные, не трогаем
    text = "гражданин А. признан виновным в краже."
    masked = mask_text(text)
    assert "гражданин А." in masked
    assert "<ФИО>" not in masked
