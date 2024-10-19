import re
from typing import Dict, Set

HAIR_PATTERNS = {
    'length': re.compile(r'(long|short|medium) hair'),
    'cut': re.compile(r'(bob|hime) cut'),
    'general': re.compile(r'([\w\-]+) hair')
}

WORD_PATTERN = re.compile(r'([\w\-]+|hair ornament)')
STYLE_PATTERN = re.compile(r'anime|cartoon|manga', re.IGNORECASE)

# 複数人がいるとき、複数の髪色や目の色が定義されていれば削除する
MULTI_PERSON_PATTERNS = [
    HAIR_PATTERNS['length'],
    HAIR_PATTERNS['cut'],
    HAIR_PATTERNS['general'],
    re.compile(r'[\w\-]+ eyes'),
    re.compile(r'([\w\-]+ sleeves|sleeveless)'),
    # 複数の髪型定義がある場合は削除する
    re.compile(r'(ponytail|braid|ahoge|twintails|[\w\-]+ bun|single hair bun|single side bun|two side up|two tails|[\w\-]+ braid|sidelocks)')
]

CAPTION_REPLACEMENTS = [
    ('anime anime', 'anime'),
    ('young ', ''),
    ('anime girl', 'girl'),
    ('cartoon female', 'girl'),
    ('cartoon lady', 'girl'),
    ('cartoon character', 'girl'),      # a or ~s
    ('cartoon woman', 'girl'),
    ('cartoon women', 'girls'),
    ('cartoon girl', 'girl'),
    ('anime female', 'girl'),
    ('anime lady', 'girl'),
    ('anime character', 'girl'),      # a or ~s
    ('anime woman', 'girl'),
    ('anime women', 'girls'),
    ('lady', 'girl'),
    ('female', 'girl'),
    ('woman', 'girl'),
    ('women', 'girls'),
    ('people', 'girls'),
    ('person', 'girl'),
    ('a cartoon figure', 'a figure'),
    ('a cartoon image', 'an image'),
    ('a cartoon picture', 'a picture'),
    ('an anime cartoon image', 'an image'),
    ('a cartoon anime drawing', 'a drawing'),
    ('a cartoon drawing', 'a drawing'),
    ('girl girl', 'girl'),
]

class TagCleaner:
    @staticmethod
    def clean_format(text: str) -> str:
        """
        テキストから無駄な記号と改行を削除
        ()をエスケープする
        Args:
            text (str): クリーニングするテキスト。
        Returns:
            str: クリーニング後のテキスト。
        """
        text = TagCleaner._clean_underscore(text) # アンダーバーをスペースに置き換える
        text = re.sub(r'#', '', text) # #を削除
        text = re.sub(r'\"', '\"', text) # ダブルクォートをエスケープ
        text = re.sub(r'\*\*', '', text) # GPT4 visionがたまに付けるマークダウンの強調を削除
        text = re.sub(r'\.\s*$', ', ', text) # ピリオドをカンマに変換
        text = re.sub(r'\.\s*(?=\S)', ', ', text)  # ピリオド後にスペースがあればカンマとスペースに置換し、新しい単語が続く場合はその前にスペースを追加
        text = re.sub(r'\.\n', ', ', text)  # 改行直前のピリオドをカンマに変換
        text = re.sub(r'\n', ', ', text) # 改行をカンマに変換
        text = re.sub(r'\u2014', '-', text) # エムダッシュをハイフンに変換
        text = re.sub(r'\(', r"\(", text)  # '(' を '\(' にエスケープ
        text = re.sub(r'\)', r"\)", text)  # ')' を '\)' にエスケープ
        return TagCleaner._clean_repetition(text) # 重複した記号を削除

    @staticmethod
    def _clean_repetition(text: str) -> str:
        """重複した記号を削除"""
        text = re.sub(r'\\+', r"\\", text) #重複した\を消す
        text = re.sub(r',+', r",", text) #重複した,を消す
        text = re.sub(r'\s+', r" ", text) #重複したスペースを消す
        return text

    @staticmethod
    def _clean_underscore(text: str) -> str:
        """アンダーバーをスペースに置き換える"""
        if not isinstance(text, str):
            return text
        # '^_^' をプレースホルダーに置き換える
        text = text.replace('^_^', '^@@@^')
        # アンダーバーを消す
        text = text.replace('_', ' ')
        # プレースホルダーを元の '^_^' に戻す
        return text.replace('^@@@^', '^_^')

    @staticmethod
    def clean_tags(tags: str) -> str:
        """タグをクリーニングする
        Args:
            tags (str): クリーニングするタグ
        Returns:
            final_tags (str): クリーニング後のタグ
        """
        tags_dict = TagCleaner._tags_to_dict(tags) # タグを辞書に変換する

        # 複数の人物がいる場合は髪色等のタグを削除する
        if 'girls' in tags or 'boys' in tags:
            tags_dict = TagCleaner._clean_individual_tags(tags_dict)

        tags_dict = TagCleaner._clean_color_object(tags_dict) # red eyesとeyesみたいな重複タグを削除
        tags_dict = TagCleaner._clean_style(tags_dict) # anime styleとanime artみたい重複タグをanimeに統一する

        final_dict = tags_dict.values()
        #カンマ区切りのstrに変換
        final_tags = ', '.join(final_dict)
        return final_tags

    @staticmethod
    def _tags_to_dict(tags: str) -> Dict[int, str]:
        """タグを辞書に変換するして重複を避ける
        Args:
            tags (str): タグ
        Returns:
            tags_dict (dict): タグの辞書
        """
        # タグをカンマで分割し、不要な空白を取り除く
        tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()]

        # 重複を避けるためのセット
        seen_tags = set()
        tags_dict = {}
        for i, tag in enumerate(tag_list):
            if tag not in seen_tags:
                seen_tags.add(tag)
                tags_dict[i] = tag
        return tags_dict

    @staticmethod
    def _clean_individual_tags(tags_dict: Dict[int, str]) -> Dict[int, str]:
        """髪の長さを残して色の特徴とかいろいろを含むタグを削除する"""
        # 置き換え用のプレースホルダー
        placeholder = "@@@"
        # 保存されたオリジナルの長さタグ
        original_lengths = {}

        # 長さに関するタグを一時的に保護
        for key, tag in tags_dict.items():
            match = HAIR_PATTERNS['length'].search(tag)
            if match:
                original_lengths[key] = match.group()  # オリジナルのタグを保存
                tags_dict[key] = tag.replace(match.group(), placeholder)

        # 不要なタグの削除
        for key, tag in tags_dict.items():
            modified_tag = tag  # 変更を加えるためのローカル変数
            for pattern in MULTI_PERSON_PATTERNS:
                modified_tag = pattern.sub("", modified_tag)
                tags_dict[key] = modified_tag  # 最終的な変更を反映

        # 髪の長さタグを復元
        for key, tag in tags_dict.items():
            if placeholder in tag:
                # placeholderをオリジナルのタグに置き換え
                tags_dict[key] = tag.replace(placeholder, original_lengths.get(key, ""))

        return tags_dict

    @staticmethod
    def _clean_color_object(tags_dict: Dict[int, str]) -> Dict[int, str]:
        """white shirtとshirtみたいな重複タグの削除"""
        # 単語の出現を記録する辞書
        word_tags: Dict[str, Set[str]] = {}

        # タグから単語を抽出し、単語が含まれるタグを記録
        for tag in tags_dict.values():
            words = WORD_PATTERN.findall(tag)
            for word in words:
                if word in word_tags:
                    word_tags[word].add(tag)
                else:
                    word_tags[word] = {tag}

        # 単語が含まれるタグが他のタグに完全に含まれているかを確認し、そのようなタグを削除
        return {k: v for k, v in tags_dict.items() if not any(v != other_tag and v in other_tag for other_tag in word_tags.get(v, set()))}

    @staticmethod
    def _clean_style(tags_dict: Dict[int, str]) -> Dict[int, str]:
        """anime styleとanime artみたい重複タグをanimeに統一する"""
        # 単語の出現を記録する辞書
        word_tags = {}

        for key, tag in tags_dict.items():
            unified_tag = tag
            match = STYLE_PATTERN.search(tag)
            if match:
                unified_tag = match.group().lower()  # 統一するタグを小文字に変換
            word_tags[key] = unified_tag

        # 重複タグの削除
        seen_tags = set()
        cleaned_tags_dict = {}
        for key, tag in word_tags.items():
            if tag not in seen_tags:
                seen_tags.add(tag)
                cleaned_tags_dict[key] = tag

        return cleaned_tags_dict

    @staticmethod
    def clean_caption(caption: str) -> str:
        """キャプションをクリーニングする
        Args:
            caption (str): クリーニングするキャプション
        """
        for rf, rt in CAPTION_REPLACEMENTS:
            replaced = True
            while replaced:
                bef = caption
                caption = caption.replace(rf, rt)
                replaced = bef != caption
        caption = caption.strip(' ,')
        return caption