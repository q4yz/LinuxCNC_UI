def test_probe(capsys):
    import sys, tests
    print('TESTS_FILE:', tests.__file__)
    for i, p in enumerate(sys.path):
        print(f'PATH{i}:', p)

