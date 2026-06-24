import random

# 1から100までのランダムな正解の数字を生成
seikai = random.randint(1, 100)
kaisuu = 0

print("==================================================")
print("🎮 数当てゲームへようこそ！")
print("ルール：1から100までの数字を当ててください。")
print("==================================================\n")

# プレイヤーが正解を当てるまでループ処理を続ける
while True:
    # ユーザーからの入力を受け取る
    yomikomi = input("数字を入力してください：")

    # 入力された文字が数字かどうかを確認（エラー処理）
    try:
        input_num = int(yomikomi)
    except ValueError:
        print("⚠️ エラー：数字（整数）を入力してください。\n")
        continue

    # 入力された数字が1〜100の範囲内かチェック
    if input_num < 1 or input_num > 100:
        print("⚠️ エラー：1から100の間の数字を入力してください。\n")
        continue

    # 挑戦回数をカウント
    kaisuu += 1

    # 正解との比較とヒントの出力
    if input_num == seikai:
        print(f"\n🎉 おめでとうございます！正解です！")
        print(f"答えは {seikai} でした。")
        print(f"あなたは {kaisuu} 回で当てました！")
        break  # 正解したのでループを抜ける
    elif input_num > seikai:
        print("📉 ヒント：もっと小さい数字です。\n")
    else:
        print("📈 ヒント：もっと大きい数字です。\n")