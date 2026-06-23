def test_package_imports():
    import hook_loop

    assert hook_loop.__version__ == "0.1.0"
    assert hook_loop.LoopDefinition is not None
    assert hook_loop.StateMachine is not None
    assert hook_loop.JsonlEventLog is not None
    assert hook_loop.LoopRuntime is not None
    assert hook_loop.LoopSpec is not None
    assert hook_loop.load_loop_spec is not None
    assert hook_loop.handle_codex_hook is not None
    assert hook_loop.install_codex_scaffold is not None
    assert hook_loop.EventSourcedLoopDriver is not None
    assert hook_loop.DefaultGuardEvaluator is not None
