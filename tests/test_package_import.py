def test_package_imports():
    import hook_loop

    assert hook_loop.__version__ == "0.1.0"
    assert hook_loop.LoopDefinition is not None
    assert hook_loop.StateMachine is not None
    assert hook_loop.JsonlEventLog is not None
    assert hook_loop.LoopRuntime is not None
    assert hook_loop.LoopSpec is not None
    assert hook_loop.load_loop_spec is not None
