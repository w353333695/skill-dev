class Provider:
    def __init__(self):
        pass

    def pre_signin(self, params):
        raise NotImplementedError(
            'this method must be implemented'
        )

    def signin(self, params):
        raise NotImplementedError(
            'this method must be implemented'
        )

    def user_info(self, authorization_info):
        raise NotImplementedError(
            'this method must be implemented'
        )

    def authorize_post_deal(self, params):
        return

    def sign_out(self, authorization_info):
        raise NotImplementedError(
            'this method must be implemented'
        )

    def custom_auth(self, params):
        raise NotImplementedError(
            'this method must be implemented'
        )

    def sso_global_sign_out(self, params):
        raise NotImplementedError(
            'this method must be implemented'
        )