from hexrdgui.indexing.fit_grains_tolerances_model import FitGrainsToleranceModel


def test_move_tolerance_rows() -> None:
    model = FitGrainsToleranceModel()
    model.update_from_config(
        {key: [1.0, 2.0, 3.0, 4.0] for key in ('tth', 'eta', 'omega')}
    )

    model.move_rows([1, 2], 1)
    for column in model.data_columns:
        assert column == [1.0, 4.0, 2.0, 3.0]

    model.move_rows([2, 3], -1)
    for column in model.data_columns:
        assert column == [1.0, 2.0, 3.0, 4.0]
