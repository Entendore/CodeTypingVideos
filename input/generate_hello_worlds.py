import os

# --- Esoteric Language Generators ---

def generate_whitespace():
    """Generates valid Whitespace code (using Space, Tab, Linefeed)"""
    S = ' '
    T = '\t'
    L = '\n'
    code = ""
    for char in "Hello, World!":
        val = ord(char)
        # Push number instruction: S S [sign] [bits] L
        sign = S # all positive
        bits = bin(val)[2:].replace('0', S).replace('1', T)
        code += S + S + sign + bits + L
        # Output character instruction: T L S S
        code += T + L + S + S
    # End program: L L L
    code += L + L + L
    return code

def generate_ook():
    """Generates Ook! code by translating the Brainfuck Hello World"""
    bf_code = '++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>.>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.>++.'
    mapping = {
        '>': 'Ook. Ook?',
        '<': 'Ook? Ook.',
        '+': 'Ook. Ook.',
        '-': 'Ook! Ook!',
        '.': 'Ook! Ook.',
        ',': 'Ook. Ook!',
        '[': 'Ook! Ook?',
        ']': 'Ook? Ook!'
    }
    return ' '.join([mapping[c] for c in bf_code if c in mapping])


# --- Language Dictionary ---

hello_worlds = {
    # 💻 The Heavyweights & Modern Languages
    "hello.py": 'print("Hello, World!")\n',
    "hello.js": 'console.log("Hello, World!");\n',
    "hello.java": 'class HelloWorld {\n    public static void main(String[] args) {\n        System.out.println("Hello, World!");\n    }\n}\n',
    "hello.c": '#include <stdio.h>\nint main() {\n    printf("Hello, World!\\n");\n    return 0;\n}\n',
    "hello.cpp": '#include <iostream>\nint main() {\n    std::cout << "Hello, World!" << std::endl;\n    return 0;\n}\n',
    "hello.cs": 'using System;\nclass Program {\n    static void Main() {\n        Console.WriteLine("Hello, World!");\n    }\n}\n',
    "hello.rs": 'fn main() {\n    println!("Hello, World!");\n}\n',
    "hello.go": 'package main\nimport "fmt"\nfunc main() {\n    fmt.Println("Hello, World!")\n}\n',
    "hello.swift": 'print("Hello, World!")\n',
    "hello.kt": 'fun main() {\n    println("Hello, World!")\n}\n',
    
    # 📜 Scripting & Dynamic
    "hello.rb": 'puts "Hello, World!"\n',
    "hello.php": '<?php\necho "Hello, World!";\n?>\n',
    "hello.pl": 'print "Hello, World!\\n";\n',
    "hello.lua": 'print("Hello, World!")\n',
    "hello.sh": '#!/bin/bash\necho "Hello, World!"\n',
    "hello.ps1": 'Write-Host "Hello, World!"\n',
    
    # 🧠 Functional & Academic
    "hello.hs": 'main = putStrLn "Hello, World!"\n',
    "hello.exs": 'IO.puts "Hello, World!"\n',
    "hello.clj": '(println "Hello, World!")\n',
    "hello.scala": '@main def hello() = println("Hello, World!")\n',
    "hello.ml": 'let () = print_endline "Hello, World!"\n',
    "hello.fs": 'printfn "Hello, World!"\n',

    # 🗄️ Data, Web & Mobile
    "hello.sql": "SELECT 'Hello, World!';\n",
    "hello.html": '<!DOCTYPE html>\n<html>\n<head><title>Hello</title></head>\n<body>Hello, World!</body>\n</html>\n',
    "hello.dart": 'void main() {\n  print(\'Hello, World!\');\n}\n',
    "hello.m": '#import <Foundation/Foundation.h>\nint main() {\n    @autoreleasepool {\n        NSLog(@"Hello, World!");\n    }\n    return 0;\n}\n',
    "hello.sol": '// SPDX-License-Identifier: MIT\npragma solidity ^0.8.0;\ncontract HelloWorld {\n    function sayHello() public pure returns (string memory) {\n        return "Hello, World!";\n    }\n}\n',
    "hello.gd": 'extends Node\n\nfunc _ready():\n    print("Hello, World!")\n',

    # 📊 Scientific
    "hello.r": 'print("Hello, World!")\n',
    "hello.jl": 'println("Hello, World!")\n',

    # 🤪 Esoteric Languages (Esolangs)
    "hello.bf": '++++++++[>++++[>++>+++>+++>+<<<<-]>+>+>->>+[<]<-]>>.>---.+++++++..+++.>>.<-.<.+++.------.--------.>>+.>++.\n',
    "hello.lol": 'HAI 1.2\nVISIBLE "Hello, World!"\nKTHXBYE\n',
    "hello.ook": generate_ook() + '\n',
    "hello.ws": generate_whitespace(),
    "hello.mal": '(=<`#9]~6ZY32Vx/4Rs+0No-&Jk)"Fh}|Bcy?`=*z]Kw%oG4UUS0/@-ejc(:\'8dcZtbZM\n',
    "hello.befunge": '<@_v#!,+"!dlroW ,olleH"<\n',
    "hello.rockstar": 'Shout "Hello, World!"\n',
    "hello.chef": """Hello World Souffle.

Ingredients.
72 g haricots
101 g eggs
108 g lard
111 g oil
32 g sugar
87 g salmon
111 g oil
114 g potatoes
108 g lard
100 g dijon mustard
33 g mustard

Method.
Put potatoes into the mixing bowl.
Put lard into the mixing bowl.
Put dijon mustard into the mixing bowl.
Put lard into the mixing bowl.
Put oil into the mixing bowl.
Put salmon into the mixing bowl.
Put sugar into the mixing bowl.
Put oil into the mixing bowl.
Put lard into the mixing bowl.
Put eggs into the mixing bowl.
Put haricots into the mixing bowl.
Liquify contents of the mixing bowl.
Pour contents of the mixing bowl into the baking dish.

Serves 1.
"""
}

def main():
    output_dir = "hello_world_files"
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Generating {len(hello_worlds)} files in '{output_dir}/'...\n")
    
    for filename, code in hello_worlds.items():
        filepath = os.path.join(output_dir, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code)
            print(f"  [+] Created: {filepath}")
        except Exception as e:
            print(f"  [-] Error creating {filepath}: {e}")
            
    print(f"\nSuccess! All files have been generated in the '{output_dir}' directory.")

if __name__ == "__main__":
    main()